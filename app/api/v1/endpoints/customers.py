"""Customer endpoints."""

from datetime import datetime, timezone
from typing import List, Union

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import verify_api_key
from app.models.customer import Customer
from app.models.order import Order
from app.schemas.customer import (
    CustomerInLookup,
    CustomerLookupRequest,
    CustomerLookupResponse,
    CustomerNotFoundResponse,
    CustomerResponse,
    DestinationInOrder,
    ESimInOrder,
    LookupSummary,
    OrderInLookup,
    OrderSummaryInLookup,
    PaymentInOrder,
    PlanInOrder,
)

router = APIRouter()


def format_payment(amount_cents: int, currency: str) -> PaymentInOrder:
    """Format payment info from cents to dollars."""
    amount = amount_cents / 100
    return PaymentInOrder(
        cents=amount_cents,
        amount=amount,
        formatted=f"${amount:.2f} {currency}",
    )


@router.post(
    "/lookup",
    response_model=Union[CustomerLookupResponse, CustomerNotFoundResponse],
    responses={
        200: {
            "description": "Customer lookup result",
            "content": {
                "application/json": {
                    "examples": {
                        "found": {
                            "summary": "Customer found",
                            "value": {
                                "success": True,
                                "customer": {
                                    "id": 123,
                                    "email": "john@example.com",
                                    "name": "John Doe",
                                    "phone": "+61412345678",
                                    "stripe_customer_id": "cus_abc123",
                                    "created_at": "2024-01-15T10:30:00Z",
                                },
                                "orders": [
                                    {
                                        "id": 456,
                                        "order_number": "TRV-20240115-001",
                                        "destination": {"slug": "japan", "name": "Japan"},
                                        "plan": {"name": "7-Day Japan", "duration_days": 7},
                                        "payment": {
                                            "cents": 2999,
                                            "amount": 29.99,
                                            "formatted": "$29.99 AUD",
                                        },
                                        "status": "paid",
                                        "esim": {
                                            "status": "delivered",
                                            "iccid": "8901234567890123456",
                                            "email_sent": True,
                                        },
                                        "created_at": "2024-01-15T10:30:00Z",
                                        "paid_at": "2024-01-15T10:31:00Z",
                                    }
                                ],
                                "summary": {
                                    "total_orders": 1,
                                    "completed_orders": 1,
                                    "total_spent": "29.99",
                                },
                                "timestamp": "2024-01-20T15:00:00Z",
                            },
                        },
                        "not_found": {
                            "summary": "Customer not found",
                            "value": {
                                "success": False,
                                "error": "Customer not found",
                                "email": "unknown@example.com",
                                "timestamp": "2024-01-20T15:00:00Z",
                            },
                        },
                    }
                }
            },
        },
    },
)
async def lookup_customer(
    request: CustomerLookupRequest,
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key),
) -> Union[CustomerLookupResponse, CustomerNotFoundResponse]:
    """Look up customer by email and return their order history.

    This endpoint is used by Aria (AI support agent) and internal tools.
    Returns customer details, all orders with eSIM status, and summary stats.

    **Matches the n8n workflow format for ElevenLabs integration.**
    """
    now = datetime.now(timezone.utc)

    # Find customer (table is "Customer" in Prisma)
    result = await db.execute(
        select(Customer).where(Customer.email == request.email)
    )
    customer = result.scalar_one_or_none()

    if not customer:
        return CustomerNotFoundResponse(
            success=False,
            error="Customer not found",
            email=request.email,
            timestamp=now,
        )

    # Get orders (eSIM data is inline on Order, no separate table)
    orders_result = await db.execute(
        select(Order)
        .where(Order.customer_id == customer.id)
        .order_by(Order.createdAt.desc())
    )
    orders = orders_result.scalars().all()

    # Build order list matching n8n format
    order_list = []
    for order in orders:
        # Get status as string
        order_status = order.status.value if hasattr(order.status, "value") else str(order.status)

        # Get eSIM status (inline on Order, not separate table)
        esim_status = order.esim_status.value if hasattr(order.esim_status, "value") else str(order.esim_status)

        order_list.append(
            OrderInLookup(
                id=order.id,
                order_number=order.order_number,
                destination=DestinationInOrder(
                    slug=order.destination_slug,
                    name=order.destination_name,
                ),
                plan=PlanInOrder(
                    name=order.plan_name,
                    duration_days=order.duration,  # Prisma uses "duration"
                ),
                payment=format_payment(order.amount_cents, order.currency),
                status=order_status,
                esim=ESimInOrder(
                    status=esim_status,
                    iccid=order.esim_iccid,
                    email_sent=order.esim_email_sent,
                ),
                created_at=order.createdAt,
                paid_at=order.paidAt,
            )
        )

    # Calculate summary
    completed_orders = [
        o for o in orders
        if (o.status.value if hasattr(o.status, "value") else str(o.status)) == "paid"
    ]
    total_spent = sum(o.amount_cents / 100 for o in completed_orders)

    return CustomerLookupResponse(
        success=True,
        customer=CustomerInLookup(
            id=customer.id,
            email=customer.email,
            name=customer.name,  # Prisma uses single "name" field
            phone=customer.phone,
            stripe_customer_id=customer.stripe_customer_id,
            created_at=customer.createdAt,  # Prisma uses camelCase
        ),
        orders=order_list,
        summary=LookupSummary(
            total_orders=len(orders),
            completed_orders=len(completed_orders),
            total_spent=f"{total_spent:.2f}",
        ),
        timestamp=now,
    )


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: int,  # Prisma uses Int for id
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key),
) -> CustomerResponse:
    """Get customer by ID."""
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalar_one_or_none()

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found",
        )

    return CustomerResponse.model_validate(customer)


@router.get("/{customer_id}/orders", response_model=List[OrderSummaryInLookup])
async def get_customer_orders(
    customer_id: int,  # Prisma uses Int for id
    db: AsyncSession = Depends(get_db),
    api_key: str = Depends(verify_api_key),
) -> List[OrderSummaryInLookup]:
    """Get all orders for a customer."""
    # Verify customer exists
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalar_one_or_none()

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found",
        )

    # Get orders
    orders_result = await db.execute(
        select(Order)
        .where(Order.customer_id == customer_id)
        .order_by(Order.createdAt.desc())
    )
    orders = orders_result.scalars().all()

    return [
        OrderSummaryInLookup(
            id=o.id,
            order_number=o.order_number,
            status=o.status.value if hasattr(o.status, "value") else str(o.status),
            destination_name=o.destination_name,
            plan_name=o.plan_name,
            duration_days=o.duration,  # Prisma uses "duration"
            amount=o.amount_cents / 100,  # Convert cents to dollars
            currency=o.currency,
            created_at=o.createdAt,  # Prisma uses camelCase
        )
        for o in orders
    ]
