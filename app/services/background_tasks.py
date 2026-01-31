"""Background tasks using FastAPI BackgroundTasks and asyncio.

No external dependencies (Redis/Celery) required.
Uses in-memory scheduling with asyncio for delayed tasks.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.core.logging import get_logger

logger = get_logger(__name__)

# In-memory storage for scheduled tasks
_scheduled_tasks: dict[str, asyncio.Task] = {}


async def schedule_delayed_task(
    task_id: str,
    delay_seconds: int,
    func: Callable,
    *args,
    **kwargs,
) -> None:
    """Schedule a task to run after a delay.

    Args:
        task_id: Unique identifier for the task (used to cancel if needed)
        delay_seconds: Seconds to wait before running
        func: Async function to run
        *args, **kwargs: Arguments to pass to the function
    """
    async def _run_after_delay():
        try:
            await asyncio.sleep(delay_seconds)
            await func(*args, **kwargs)
        except asyncio.CancelledError:
            logger.info("scheduled_task_cancelled", task_id=task_id)
        except Exception as e:
            logger.error("scheduled_task_failed", task_id=task_id, error=str(e))
        finally:
            _scheduled_tasks.pop(task_id, None)

    # Cancel existing task with same ID if exists
    if task_id in _scheduled_tasks:
        _scheduled_tasks[task_id].cancel()

    task = asyncio.create_task(_run_after_delay())
    _scheduled_tasks[task_id] = task

    logger.info(
        "task_scheduled",
        task_id=task_id,
        run_at=datetime.now(timezone.utc) + timedelta(seconds=delay_seconds),
    )


def cancel_scheduled_task(task_id: str) -> bool:
    """Cancel a scheduled task by ID."""
    task = _scheduled_tasks.pop(task_id, None)
    if task:
        task.cancel()
        return True
    return False


async def schedule_connection_guarantee_check(
    order_id: int,
    delay_minutes: int = 10,
) -> None:
    """Schedule a connection guarantee check task.

    Called after QR code delivery to check activation after 10 minutes.
    Note: This is a placeholder - actual guarantee check requires
    integration with eSIM provider API to verify activation status.
    """
    from app.core.database import async_session_maker
    from app.models.order import Order, EsimStatus
    from app.services.notification_service import NotificationService

    async def check_guarantee():
        async with async_session_maker() as db:
            order = await db.get(Order, order_id)
            if not order:
                logger.error("guarantee_check_order_not_found", order_id=order_id)
                return

            # If already activated or refunded, skip
            if order.esim_status == EsimStatus.activated:
                logger.info("guarantee_check_already_activated", order_id=order_id)
                return

            if order.status.value == "refunded":
                logger.info("guarantee_check_already_refunded", order_id=order_id)
                return

            # TODO: Check activation status with eSIM provider
            # For now, just log that the check was performed
            logger.info(
                "guarantee_check_completed",
                order_id=order_id,
                esim_status=order.esim_status.value,
            )

            # If not activated, notify support team
            if order.esim_status != EsimStatus.activated:
                notifications = NotificationService()
                await notifications._send_message(
                    notifications.alerts_chat_id,
                    f"<b>Guarantee Check Alert</b>\n\n"
                    f"Order {order.order_number} not activated after 10 minutes.\n"
                    f"eSIM Status: {order.esim_status.value}\n"
                    f"Customer may need assistance.",
                )

    task_id = f"guarantee_check_{order_id}"
    await schedule_delayed_task(
        task_id=task_id,
        delay_seconds=delay_minutes * 60,
        func=check_guarantee,
    )


async def resend_failed_delivery(order_id: int, delay_minutes: int = 5) -> None:
    """Schedule a retry for failed QR code delivery."""
    from sqlalchemy import select

    from app.core.database import async_session_maker
    from app.models.customer import Customer
    from app.models.order import Order
    from app.services.delivery_service import DeliveryService
    from app.services.esim_service import ESimService

    async def retry_delivery():
        async with async_session_maker() as db:
            result = await db.execute(select(Order).where(Order.id == order_id))
            order = result.scalar_one_or_none()

            if not order or not order.esim_qr_code:
                logger.error("delivery_retry_order_not_found", order_id=order_id)
                return

            customer = await db.get(Customer, order.customer_id)
            if not customer:
                logger.error("delivery_retry_customer_not_found", order_id=order_id)
                return

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

            if delivery_result.get("success"):
                order.esim_email_sent = True
                await db.commit()

            logger.info(
                "delivery_retry_completed",
                order_id=order_id,
                success=delivery_result.get("success"),
            )

    task_id = f"delivery_retry_{order_id}"
    await schedule_delayed_task(
        task_id=task_id,
        delay_seconds=delay_minutes * 60,
        func=retry_delivery,
    )
