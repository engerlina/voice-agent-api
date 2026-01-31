"""Order endpoints."""

from datetime import datetime, timezone
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import verify_api_key
from app.models.customer import Customer
from app.models.order import Order
from app.schemas.order import (
    ESimInfo,
    OrderResponse,
    ProcessRefundRequest,
    ProcessRefundResponse,
    ProcessRefundErrorResponse,
    RefundRequest,
    RefundResponse,
    ResendQRRequest,
    ResendQRResponse,
    ResendQRErrorResponse,
)
from app.services.order_service import OrderService

router = APIRouter()


def get_order_service() -> OrderService:
    """Dependency for order service."""
    return OrderService()


def order_to_response(order: Order) -> OrderResponse:
    """Convert Order model to OrderResponse schema."""
    return OrderResponse(
        id=order.id,
        order_number=order.order_number,
        customer_id=order.customer_id,
        status=order.status.value if hasattr(order.status, "value") else str(order.status),
        destination_slug=order.destination_slug,
        destination_name=order.destination_name,
        plan_name=order.plan_name,
        bundle_name=order.bundle_name,
        duration=order.duration,
        amount_cents=order.amount_cents,
        currency=order.currency,
        stripe_session_id=order.stripe_session_id,
        stripe_payment_intent_id=order.stripe_payment_intent_id,
        esim=ESimInfo(
            status=order.esim_status.value if hasattr(order.esim_status, "value") else str(order.esim_status),
            iccid=order.esim_iccid,
            smdp_address=order.esim_smdp_address,
            matching_id=order.esim_matching_id,
            qr_code=order.esim_qr_code,
            order_ref=order.esim_order_ref,
            provisioned_at=order.esim_provisioned_at,
        ),
        locale=order.locale,
        createdAt=order.createdAt,
        updatedAt=order.updatedAt,
        paidAt=order.paidAt,
    )


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key),
) -> OrderResponse:
    """Get order by ID with eSIM details."""
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    return order_to_response(order)


@router.get("/by-number/{order_number}", response_model=OrderResponse)
async def get_order_by_number(
    order_number: str,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key),
) -> OrderResponse:
    """Get order by order number (e.g., TRV-20240115-001)."""
    result = await db.execute(select(Order).where(Order.order_number == order_number))
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    return order_to_response(order)


@router.post("/{order_id}/refund", response_model=RefundResponse)
async def refund_order(
    order_id: int,
    request: RefundRequest,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key),
    order_service: OrderService = Depends(get_order_service),
) -> RefundResponse:
    """Process a refund for an order.

    Trvel policy: No forms, no questions refunds.
    """
    if request.order_id != order_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Order ID mismatch",
        )

    try:
        return await order_service.process_refund(db, request)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/{order_id}/resend-qr")
async def resend_qr_code_by_id(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key),
) -> dict:
    """Resend QR code to customer (legacy endpoint, uses auto channel)."""
    from app.services.delivery_service import DeliveryService
    from app.services.esim_service import ESimService

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    if not order.esim_qr_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No QR code found for this order",
        )

    customer = await db.get(Customer, order.customer_id)
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Customer not found",
        )

    # Generate QR image and resend
    esim_service = ESimService()
    delivery_service = DeliveryService()

    qr_image = esim_service._generate_qr_image(order.esim_qr_code)

    delivery_result = await delivery_service.deliver_qr_code(
        customer_email=customer.email,
        customer_phone=customer.phone,
        customer_name=customer.name,
        order_number=order.order_number,
        destination=order.destination_name,
        plan_name=order.plan_name,
        duration_days=order.duration,
        qr_code_image=qr_image,
        qr_code_data=order.esim_qr_code,
        activation_code=order.esim_matching_id,
        sm_dp_address=order.esim_smdp_address,
    )

    return {
        "success": delivery_result.get("success", False),
        "channel": delivery_result.get("channel"),
        "message": "QR code resent" if delivery_result.get("success") else "Resend failed",
    }


@router.post(
    "/resend-qr",
    response_model=Union[ResendQRResponse, ResendQRErrorResponse],
    responses={
        200: {
            "description": "QR code resend result",
            "content": {
                "application/json": {
                    "examples": {
                        "success_email": {
                            "summary": "Email resend success",
                            "value": {
                                "success": True,
                                "order_id": 123,
                                "order_number": "TRV-20240115-001",
                                "customer_email": "customer@example.com",
                                "destination_name": "Japan",
                                "plan_name": "Week Explorer",
                                "channel_used": "email",
                                "message_id": "msg_xxx",
                                "message": "QR code sent to customer@example.com",
                                "timestamp": "2024-01-20T15:00:00Z",
                            },
                        },
                        "success_sms": {
                            "summary": "SMS resend success",
                            "value": {
                                "success": True,
                                "order_id": 123,
                                "order_number": "TRV-20240115-001",
                                "customer_email": "customer@example.com",
                                "destination_name": "Japan",
                                "plan_name": "Week Explorer",
                                "channel_used": "sms",
                                "message_id": "SM_xxx",
                                "message": "QR code link sent to ****1234",
                                "timestamp": "2024-01-20T15:00:00Z",
                            },
                        },
                        "error": {
                            "summary": "Order not found",
                            "value": {
                                "success": False,
                                "error": "Order not found",
                                "order_number": "TRV-20240115-999",
                                "timestamp": "2024-01-20T15:00:00Z",
                            },
                        },
                    }
                }
            },
        },
    },
)
async def resend_qr_code(
    request: ResendQRRequest,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key),
) -> Union[ResendQRResponse, ResendQRErrorResponse]:
    """Resend QR code through specified channel.

    This endpoint is used by:
    - Aria (AI chat support) to resend QR codes via email
    - Phone support to resend via SMS

    Channels:
    - 'email': Send QR code to customer's email
    - 'sms': Send QR code link to customer's phone
    - 'auto': Try email first, then SMS as fallback

    You can lookup the order by:
    - order_id: The numeric order ID
    - order_number: The order reference (e.g., TRV-20240115-001)
    - customer_email: Find the most recent order for this email
    """
    from app.services.delivery_service import DeliveryService
    from app.services.esim_service import ESimService

    now = datetime.now(timezone.utc)

    # Find the order
    order = None
    if request.order_id:
        result = await db.execute(select(Order).where(Order.id == request.order_id))
        order = result.scalar_one_or_none()
    elif request.order_number:
        result = await db.execute(
            select(Order).where(Order.order_number == request.order_number)
        )
        order = result.scalar_one_or_none()
    elif request.customer_email:
        # Find the most recent order for this customer
        result = await db.execute(
            select(Order)
            .join(Customer)
            .where(Customer.email == request.customer_email.lower())
            .order_by(Order.createdAt.desc())
            .limit(1)
        )
        order = result.scalar_one_or_none()
    else:
        return ResendQRErrorResponse(
            success=False,
            error="Must provide order_id, order_number, or customer_email",
            timestamp=now,
        )

    if not order:
        return ResendQRErrorResponse(
            success=False,
            error="Order not found",
            order_id=request.order_id,
            order_number=request.order_number,
            timestamp=now,
        )

    if not order.esim_qr_code:
        return ResendQRErrorResponse(
            success=False,
            error="No QR code available for this order. The eSIM may still be processing.",
            order_id=order.id,
            order_number=order.order_number,
            timestamp=now,
        )

    # Get customer
    customer = await db.get(Customer, order.customer_id)
    if not customer:
        return ResendQRErrorResponse(
            success=False,
            error="Customer record not found",
            order_id=order.id,
            order_number=order.order_number,
            timestamp=now,
        )

    # Verify email matches if provided (security check)
    if request.customer_email and customer.email.lower() != request.customer_email.lower():
        return ResendQRErrorResponse(
            success=False,
            error="Email does not match order records",
            order_id=order.id,
            order_number=order.order_number,
            timestamp=now,
        )

    # Determine phone number to use
    phone_to_use = request.phone_override or customer.phone

    # Generate QR image and resend
    esim_service = ESimService()
    delivery_service = DeliveryService()

    try:
        qr_image = esim_service._generate_qr_image(order.esim_qr_code)
    except Exception as e:
        return ResendQRErrorResponse(
            success=False,
            error=f"Failed to generate QR code image: {str(e)}",
            order_id=order.id,
            order_number=order.order_number,
            timestamp=now,
        )

    # Send through specified channel
    delivery_result = await delivery_service.resend_qr_code(
        channel=request.channel,
        customer_email=customer.email,
        customer_phone=phone_to_use,
        customer_name=customer.name or "Traveler",
        order_number=order.order_number,
        destination=order.destination_name,
        plan_name=order.plan_name,
        duration_days=order.duration,
        qr_code_image=qr_image,
        qr_code_data=order.esim_qr_code,
        activation_code=order.esim_matching_id,
        sm_dp_address=order.esim_smdp_address,
    )

    if delivery_result.get("success"):
        return ResendQRResponse(
            success=True,
            order_id=order.id,
            order_number=order.order_number,
            customer_email=customer.email,
            destination_name=order.destination_name,
            plan_name=order.plan_name,
            channel_used=delivery_result.get("channel"),
            message_id=delivery_result.get("message_id"),
            message=delivery_result.get("message", "QR code sent"),
            timestamp=now,
        )
    else:
        return ResendQRErrorResponse(
            success=False,
            error=delivery_result.get("message", "Failed to resend QR code"),
            order_id=order.id,
            order_number=order.order_number,
            timestamp=now,
        )


@router.post(
    "/process-refund",
    response_model=Union[ProcessRefundResponse, ProcessRefundErrorResponse],
    responses={
        200: {
            "description": "Refund processing result",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "Refund processed successfully",
                            "value": {
                                "success": True,
                                "order_id": 123,
                                "order_number": "TRV-20250115-001",
                                "customer_email": "customer@example.com",
                                "destination_name": "Japan",
                                "plan_name": "Week Explorer",
                                "amount_refunded": 29.99,
                                "currency": "AUD",
                                "stripe_refund_id": "re_xxx",
                                "esim_bundle_revoked": True,
                                "esim_bundle_refunded": True,
                                "steps": [
                                    {"step": "eligibility_check", "success": True, "message": "eSIM not activated"},
                                    {"step": "bundle_revoke", "success": True, "message": "Bundle revoked"},
                                    {"step": "bundle_refund", "success": True, "message": "Bundle refunded to balance"},
                                    {"step": "stripe_refund", "success": True, "message": "Payment refunded"},
                                    {"step": "email_notification", "success": True, "message": "Confirmation sent"},
                                ],
                                "message": "Full refund processed: $29.99 AUD refunded to customer",
                                "timestamp": "2025-01-20T15:00:00Z",
                            },
                        },
                        "esim_activated": {
                            "summary": "Refund denied - eSIM was used",
                            "value": {
                                "success": False,
                                "error": "eSIM has been activated and used 0.5 MB of data. Refunds are only available for unused eSIMs.",
                                "error_code": "esim_activated",
                                "order_id": 123,
                                "order_number": "TRV-20250115-001",
                                "customer_email": "customer@example.com",
                                "destination_name": "Japan",
                                "data_used_mb": 0.5,
                                "timestamp": "2025-01-20T15:00:00Z",
                            },
                        },
                        "already_refunded": {
                            "summary": "Order already refunded",
                            "value": {
                                "success": False,
                                "error": "This order has already been refunded",
                                "error_code": "already_refunded",
                                "order_id": 123,
                                "order_number": "TRV-20250115-001",
                                "timestamp": "2025-01-20T15:00:00Z",
                            },
                        },
                    }
                }
            },
        },
    },
)
async def process_full_refund(
    request: ProcessRefundRequest,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key),
    order_service: OrderService = Depends(get_order_service),
) -> Union[ProcessRefundResponse, ProcessRefundErrorResponse]:
    """Process a full refund with eSIM bundle recovery.

    This endpoint is used by:
    - Aria (AI chat support) to process refund requests
    - Phone support agents to process refunds

    Refund workflow:
    1. Verify eSIM has NOT been activated (no data used)
    2. Revoke the bundle from eSIM Go (returns to inventory)
    3. Refund the bundle to organization balance
    4. Process Stripe refund to customer
    5. Send confirmation email

    If eSIM was activated (any data used), refund is DENIED unless force=True.
    Force is only for guarantee cases where we promised connection in 10 minutes.

    You can lookup the order by:
    - order_id: The numeric order ID
    - order_number: The order reference (e.g., TRV-20250115-001)
    - customer_email: Find the most recent paid order for this email
    """
    return await order_service.process_full_refund(db, request)
