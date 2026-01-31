"""Stripe payment integration service."""

from decimal import Decimal
from typing import Optional

import stripe
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Initialize Stripe with active key (respects test mode)
stripe.api_key = settings.active_stripe_secret_key


# Map duration days to friendly plan names
PLAN_NAME_MAP = {
    1: "Day Pass",
    3: "Weekend Explorer",
    5: "Week Starter",
    7: "Week Explorer",
    10: "Extended Stay",
    15: "Two Week Adventure",
    30: "Monthly Explorer",
}


def get_plan_name(duration: int) -> str:
    """Get friendly plan name for duration."""
    return PLAN_NAME_MAP.get(duration, f"{duration}-Day Plan")


class StripeService:
    """Service for Stripe payment operations."""

    def __init__(self):
        self.webhook_secret = settings.active_stripe_webhook_secret
        self.website_url = settings.website_url

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def create_checkout_session(
        self,
        destination_slug: str,
        destination_name: str,
        duration: int,
        price: float,
        currency: str,
        bundle_name: str,
        locale: str = "en-au",
        promo_code: Optional[str] = None,
        customer_email: Optional[str] = None,
        customer_phone: Optional[str] = None,
    ) -> dict:
        """Create a Stripe Checkout session.

        This creates a hosted checkout page URL that customers can use to pay.
        Used for chat/SMS payment links.

        Args:
            destination_slug: e.g., "japan"
            destination_name: e.g., "Japan"
            duration: Duration in days
            price: Price in the currency (not cents)
            currency: Currency code (e.g., "AUD")
            bundle_name: eSIM Go bundle name for provisioning
            locale: Customer locale
            promo_code: Optional promo code to apply
            customer_email: Optional customer email to prefill
            customer_phone: Optional customer phone for order tracking

        Returns:
            dict with 'url' (checkout URL) and 'session_id'
        """
        try:
            plan_name = get_plan_name(duration)
            product_name = f"{destination_name} eSIM - {plan_name}"
            price_in_cents = int(round(price * 100))

            # Build checkout session options
            session_options = {
                "mode": "payment",
                "payment_method_types": ["card"],
                "line_items": [
                    {
                        "price_data": {
                            "currency": currency.lower(),
                            "product_data": {
                                "name": product_name,
                                "description": f"{duration}-day unlimited data eSIM for {destination_name}",
                                "metadata": {
                                    "destination_slug": destination_slug,
                                    "duration": str(duration),
                                    "locale": locale,
                                },
                            },
                            "unit_amount": price_in_cents,
                        },
                        "quantity": 1,
                    },
                ],
                "success_url": f"{self.website_url}/{locale}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}",
                "cancel_url": f"{self.website_url}/{locale}/checkout/cancel",
                "metadata": {
                    "destination_slug": destination_slug,
                    "destination_name": destination_name,
                    "duration": str(duration),
                    "locale": locale,
                    "bundle_name": bundle_name,
                    "price_paid": str(price),
                    "currency": currency.upper(),
                    "source": "api",  # Mark as coming from API (chat/SMS)
                },
                "allow_promotion_codes": True,
            }

            # Prefill customer email if provided
            if customer_email:
                session_options["customer_email"] = customer_email

            # Apply promo code if provided
            if promo_code:
                try:
                    promotion_codes = stripe.PromotionCode.list(
                        code=promo_code,
                        active=True,
                        limit=1,
                    )
                    if promotion_codes.data:
                        session_options["discounts"] = [
                            {"promotion_code": promotion_codes.data[0].id}
                        ]
                        # Remove allow_promotion_codes when applying specific code
                        session_options.pop("allow_promotion_codes", None)
                except stripe.error.StripeError:
                    # If promo code lookup fails, just allow manual entry
                    pass

            # Add phone to metadata for SMS order tracking
            if customer_phone:
                session_options["metadata"]["customer_phone"] = customer_phone

            # Create the session
            session = stripe.checkout.Session.create(**session_options)

            logger.info(
                "checkout_session_created",
                session_id=session.id,
                destination=destination_slug,
                duration=duration,
                price=price,
                currency=currency,
            )

            return {
                "url": session.url,
                "session_id": session.id,
            }

        except stripe.error.StripeError as e:
            logger.error(
                "checkout_session_failed",
                destination=destination_slug,
                error=str(e),
            )
            raise

    def verify_webhook_signature(self, payload: bytes, signature: str) -> dict:
        """Verify Stripe webhook signature and return event."""
        try:
            event = stripe.Webhook.construct_event(
                payload, signature, self.webhook_secret
            )
            return event
        except stripe.error.SignatureVerificationError as e:
            logger.error("webhook_signature_invalid", error=str(e))
            raise ValueError("Invalid webhook signature") from e
        except Exception as e:
            logger.error("webhook_verification_failed", error=str(e))
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def create_payment_intent(
        self,
        amount: Decimal,
        currency: str,
        customer_email: str,
        metadata: dict,
    ) -> stripe.PaymentIntent:
        """Create a Stripe PaymentIntent."""
        try:
            # Amount in cents
            amount_cents = int(amount * 100)

            intent = stripe.PaymentIntent.create(
                amount=amount_cents,
                currency=currency.lower(),
                receipt_email=customer_email,
                metadata=metadata,
                automatic_payment_methods={"enabled": True},
            )

            logger.info(
                "payment_intent_created",
                intent_id=intent.id,
                amount=amount_cents,
                currency=currency,
            )

            return intent
        except stripe.error.StripeError as e:
            logger.error("payment_intent_failed", error=str(e))
            raise

    async def get_payment_intent(self, payment_intent_id: str) -> stripe.PaymentIntent:
        """Retrieve a PaymentIntent by ID."""
        try:
            return stripe.PaymentIntent.retrieve(payment_intent_id)
        except stripe.error.StripeError as e:
            logger.error(
                "payment_intent_retrieval_failed",
                payment_intent_id=payment_intent_id,
                error=str(e),
            )
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def create_refund(
        self,
        payment_intent_id: str,
        amount: Optional[Decimal] = None,
        reason: Optional[str] = None,
    ) -> stripe.Refund:
        """Create a refund for a payment.

        Args:
            payment_intent_id: The PaymentIntent to refund
            amount: Amount to refund (in dollars). If None, full refund.
            reason: Reason for the refund (duplicate, fraudulent, requested_by_customer)
        """
        try:
            params = {"payment_intent": payment_intent_id}

            if amount is not None:
                params["amount"] = int(amount * 100)  # Convert to cents

            if reason:
                # Map to Stripe's valid reasons
                valid_reasons = ["duplicate", "fraudulent", "requested_by_customer"]
                if reason in valid_reasons:
                    params["reason"] = reason

            refund = stripe.Refund.create(**params)

            logger.info(
                "refund_created",
                refund_id=refund.id,
                payment_intent_id=payment_intent_id,
                amount=amount,
            )

            return refund
        except stripe.error.StripeError as e:
            logger.error(
                "refund_failed",
                payment_intent_id=payment_intent_id,
                error=str(e),
            )
            raise

    async def get_or_create_customer(
        self,
        email: str,
        name: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> stripe.Customer:
        """Get existing Stripe customer or create new one."""
        try:
            # Search for existing customer
            customers = stripe.Customer.list(email=email, limit=1)
            if customers.data:
                customer = customers.data[0]
                logger.info("stripe_customer_found", customer_id=customer.id)
                return customer

            # Create new customer
            customer = stripe.Customer.create(
                email=email,
                name=name,
                phone=phone,
            )
            logger.info("stripe_customer_created", customer_id=customer.id)
            return customer
        except stripe.error.StripeError as e:
            logger.error("stripe_customer_operation_failed", error=str(e))
            raise

    def parse_payment_succeeded_event(self, event_data: dict) -> dict:
        """Parse payment.intent.succeeded event data."""
        payment_intent = event_data.get("object", {})
        return {
            "payment_intent_id": payment_intent.get("id"),
            "amount": Decimal(payment_intent.get("amount", 0)) / 100,
            "currency": payment_intent.get("currency", "").upper(),
            "customer_id": payment_intent.get("customer"),
            "receipt_email": payment_intent.get("receipt_email"),
            "metadata": payment_intent.get("metadata", {}),
            "status": payment_intent.get("status"),
        }

    def parse_checkout_completed_event(self, event_data: dict) -> dict:
        """Parse checkout.session.completed event data."""
        session = event_data.get("object", {})
        customer_details = session.get("customer_details", {})
        metadata = session.get("metadata", {})

        return {
            "session_id": session.get("id"),
            "payment_intent_id": session.get("payment_intent"),
            "amount_total": session.get("amount_total", 0) / 100,
            "currency": session.get("currency", "").upper(),
            "customer_email": customer_details.get("email"),
            "customer_name": customer_details.get("name"),
            "customer_phone": customer_details.get("phone") or metadata.get("customer_phone"),
            "destination_slug": metadata.get("destination_slug"),
            "destination_name": metadata.get("destination_name"),
            "duration": int(metadata.get("duration", 0)),
            "bundle_name": metadata.get("bundle_name"),
            "locale": metadata.get("locale", "en-au"),
            "source": metadata.get("source", "website"),
        }
