"""AI-powered support triage service - stateless, no database persistence."""

import json
import time
from datetime import datetime, timezone
from typing import Optional

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.customer import Customer
from app.models.order import Order
from app.schemas.support import SupportTriageRequest, SupportTriageResponse

logger = get_logger(__name__)


class SupportService:
    """AI-powered support triage service.

    This is a stateless service - no tickets are persisted.
    It classifies support requests and generates suggested responses.
    Results should be forwarded to an external ticketing system if needed.
    """

    # Categories that can be auto-responded without human review
    AUTO_RESPONSE_CATEGORIES = ["general", "activation"]

    # High-confidence threshold for auto-response
    AUTO_RESPONSE_CONFIDENCE = 0.85

    def __init__(self):
        self.openai = AsyncOpenAI(api_key=settings.openai_api_key)

    async def triage_support_request(
        self,
        db: AsyncSession,
        request: SupportTriageRequest,
    ) -> SupportTriageResponse:
        """Triage incoming support request with AI.

        1. Classify the issue category and priority
        2. Look up related customer/order data for context
        3. Generate suggested response
        4. Return classification and response (no persistence)
        """
        start_time = time.time()
        now = datetime.now(timezone.utc)

        # Look up customer and related order for context
        customer = None
        related_order = None

        if request.customer_email:
            result = await db.execute(
                select(Customer).where(Customer.email == request.customer_email)
            )
            customer = result.scalar_one_or_none()

        if request.order_id:
            result = await db.execute(
                select(Order).where(Order.id == request.order_id)
            )
            related_order = result.scalar_one_or_none()

        # Build context for AI
        customer_context = self._build_customer_context(customer, related_order)

        # AI classification
        classification = await self._classify_with_ai(
            subject=request.subject,
            message=request.message,
            customer_context=customer_context,
        )

        # Generate suggested response
        suggested_response = await self._generate_response(
            category=classification["category"],
            subject=request.subject,
            message=request.message,
            customer_context=customer_context,
        )

        # Determine if human review needed
        requires_human = (
            classification["category"] not in self.AUTO_RESPONSE_CATEGORIES
            or classification["confidence"] < self.AUTO_RESPONSE_CONFIDENCE
            or classification.get("requires_human", True)
        )

        processing_time_ms = int((time.time() - start_time) * 1000)

        logger.info(
            "support_triage_completed",
            category=classification["category"],
            priority=classification["priority"],
            confidence=classification["confidence"],
            requires_human=requires_human,
            processing_time_ms=processing_time_ms,
        )

        return SupportTriageResponse(
            category=classification["category"],
            priority=classification["priority"],
            confidence=classification["confidence"],
            suggested_response=suggested_response,
            requires_human=requires_human,
            related_order=(
                {"id": related_order.id, "order_number": related_order.order_number}
                if related_order
                else None
            ),
            customer_found=customer is not None,
            processing_time_ms=processing_time_ms,
            timestamp=now,
        )

    async def _classify_with_ai(
        self,
        subject: str,
        message: str,
        customer_context: str,
    ) -> dict:
        """Use AI to classify the support request."""
        system_prompt = """You are a support triage AI for Trvel, a travel eSIM provider.

Classify the customer's support request into:

CATEGORIES:
- activation: Issues connecting or activating the eSIM
- delivery: QR code not received or can't scan
- refund: Refund requests
- billing: Payment questions, pricing
- technical: Device compatibility, settings issues
- general: General questions about products/service
- feedback: Feedback or suggestions

PRIORITIES:
- urgent: Customer traveling now and can't connect (needs immediate help)
- high: Delivery failure, activation failure within guarantee period
- medium: Pre-travel questions, billing issues
- low: General inquiries, feedback

Return JSON with:
- category: one of the categories above
- priority: one of the priorities above
- confidence: 0.0 to 1.0 confidence in classification
- requires_human: true if this needs human attention
- summary: brief 1-2 sentence summary of the issue
"""

        user_prompt = f"""Subject: {subject}

Message:
{message}

{customer_context}

Classify this support request."""

        try:
            response = await self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )

            result = json.loads(response.choices[0].message.content)
            return {
                "category": result.get("category", "general"),
                "priority": result.get("priority", "medium"),
                "confidence": float(result.get("confidence", 0.5)),
                "requires_human": result.get("requires_human", True),
                "summary": result.get("summary", ""),
            }
        except Exception as e:
            logger.error("ai_classification_failed", error=str(e))
            return {
                "category": "general",
                "priority": "medium",
                "confidence": 0.0,
                "requires_human": True,
                "summary": "",
            }

    async def _generate_response(
        self,
        category: str,
        subject: str,
        message: str,
        customer_context: str,
    ) -> str:
        """Generate a helpful response using AI."""
        system_prompt = """You are Aria, the friendly AI support assistant for Trvel, a premium travel eSIM provider.

Your role:
- Provide helpful, accurate answers about eSIMs and Trvel services
- Be warm but professional
- Keep responses concise (2-4 paragraphs max)
- Include relevant next steps
- Mention the 10-minute connection guarantee when relevant
- Offer to escalate if you can't fully help

Key Trvel info:
- Instant QR code delivery after purchase
- 1GB daily high-speed data, unlimited at 1.25 Mbps after
- 10-minute connection guarantee (refund if not connected in 10 min)
- 24/7 support, 3-minute response target
- No-questions-asked refunds

For activation issues, guide them through:
1. Connect to WiFi first
2. Settings > Cellular/Mobile > Add eSIM
3. Scan the QR code from their email
4. Enable the eSIM line when they arrive at destination
"""

        user_prompt = f"""Customer inquiry:
Subject: {subject}
Message: {message}

{customer_context}

Generate a helpful response."""

        try:
            response = await self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                max_tokens=500,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error("ai_response_generation_failed", error=str(e))
            return self._get_fallback_response(category)

    def _build_customer_context(
        self,
        customer: Optional[Customer],
        order: Optional[Order],
    ) -> str:
        """Build context string for AI from customer data."""
        if not customer and not order:
            return "Customer context: Unknown customer"

        context_parts = []
        if customer:
            context_parts.append(f"Customer: {customer.name or 'Unknown'} ({customer.email})")

        if order:
            # Get status as string
            order_status = order.status.value if hasattr(order.status, "value") else str(order.status)
            esim_status = order.esim_status.value if hasattr(order.esim_status, "value") else str(order.esim_status)

            context_parts.append(
                f"Recent order: #{order.order_number}, "
                f"Destination: {order.destination_name}, "
                f"Status: {order_status}, "
                f"eSIM Status: {esim_status}, "
                f"Created: {order.createdAt.strftime('%Y-%m-%d')}"
            )
            if order.esim_email_sent:
                context_parts.append("QR code has been sent to customer")

        return "Customer context:\n" + "\n".join(context_parts)

    def _get_fallback_response(self, category: str) -> str:
        """Get fallback response when AI fails."""
        fallbacks = {
            "activation": (
                "I'm sorry you're having trouble activating your eSIM. "
                "Please make sure you're connected to WiFi and try these steps:\n\n"
                "1. Go to Settings > Cellular/Mobile > Add eSIM\n"
                "2. Scan the QR code from your confirmation email\n"
                "3. Enable the eSIM when you arrive at your destination\n\n"
                "If you're still having issues, a member of our team will be with you shortly. "
                "Remember, if you can't connect within 10 minutes of arriving, "
                "we'll refund you automatically!"
            ),
            "delivery": (
                "I'm sorry you haven't received your eSIM QR code. "
                "Please check your spam folder first. "
                "If you still can't find it, our team will resend it to you right away. "
                "Someone will be in touch within the next few minutes."
            ),
            "refund": (
                "I understand you'd like a refund. At Trvel, we have a no-questions-asked refund policy. "
                "A member of our team will process your refund shortly. "
                "You should see the funds back in your account within 5-10 business days."
            ),
            "default": (
                "Thank you for reaching out! I'm connecting you with our support team "
                "who will be able to help you further. Someone will be in touch within "
                "the next few minutes."
            ),
        }
        return fallbacks.get(category, fallbacks["default"])
