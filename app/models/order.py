"""Order database model - matches Prisma schema."""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.customer import Customer


class OrderStatus(str, Enum):
    """Order status enum - matches Prisma OrderStatus."""

    pending = "pending"
    paid = "paid"
    failed = "failed"
    refunded = "refunded"
    disputed = "disputed"


class EsimStatus(str, Enum):
    """eSIM status enum - matches Prisma EsimStatus."""

    pending = "pending"  # Payment received, not yet ordered from eSIM-Go
    ordering = "ordering"  # API call in progress
    ordered = "ordered"  # Successfully ordered from eSIM-Go
    delivered = "delivered"  # Email with QR code sent
    activated = "activated"  # Customer activated the eSIM
    failed = "failed"  # Order failed


class Order(Base):
    """Order model - matches Prisma schema exactly.

    Prisma schema:
        model Order {
            id                       Int         @id @default(autoincrement())
            order_number             String      @unique @db.VarChar(20)
            customer_id              Int
            destination_slug         String      @db.VarChar(50)
            destination_name         String      @db.VarChar(100)
            duration                 Int
            plan_name                String      @db.VarChar(50)
            bundle_name              String?     @db.VarChar(100)
            amount_cents             Int
            currency                 String      @db.Char(3)
            status                   OrderStatus @default(pending)
            stripe_session_id        String?     @unique @db.VarChar(100)
            stripe_payment_intent_id String?     @db.VarChar(100)
            esim_status              EsimStatus  @default(pending)
            esim_iccid               String?     @db.VarChar(50)
            esim_smdp_address        String?     @db.VarChar(200)
            esim_matching_id         String?     @db.VarChar(200)
            esim_qr_code             String?     @db.Text
            esim_order_ref           String?     @db.VarChar(100)
            esim_provisioned_at      DateTime?
            confirmation_email_sent  Boolean     @default(false)
            esim_email_sent          Boolean     @default(false)
            locale                   String      @db.VarChar(10)
            notes                    String?     @db.Text
            createdAt                DateTime    @default(now())
            updatedAt                DateTime    @updatedAt
            paidAt                   DateTime?
        }
    """

    __tablename__ = "Order"  # Prisma uses PascalCase table names

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("Customer.id"), nullable=False
    )

    # Product details
    destination_slug: Mapped[str] = mapped_column(String(50), nullable=False)
    destination_name: Mapped[str] = mapped_column(String(100), nullable=False)
    duration: Mapped[int] = mapped_column(Integer, nullable=False)  # Days
    plan_name: Mapped[str] = mapped_column(String(50), nullable=False)
    bundle_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Payment details
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        String(20), default=OrderStatus.pending, index=True
    )

    # Stripe references
    stripe_session_id: Mapped[Optional[str]] = mapped_column(
        String(100), unique=True, nullable=True
    )
    stripe_payment_intent_id: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )

    # eSIM fulfillment (inline, not separate table)
    esim_status: Mapped[EsimStatus] = mapped_column(
        String(20), default=EsimStatus.pending, index=True
    )
    esim_iccid: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    esim_smdp_address: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    esim_matching_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    esim_qr_code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    esim_order_ref: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    esim_provisioned_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Communication
    confirmation_email_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    esim_email_sent: Mapped[bool] = mapped_column(Boolean, default=False)

    # Support
    locale: Mapped[str] = mapped_column(String(10), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps (Prisma uses camelCase)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paidAt: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    customer: Mapped["Customer"] = relationship("Customer", back_populates="orders")

    # Compatibility properties for existing code
    @property
    def duration_days(self) -> int:
        """Alias for duration for backwards compatibility."""
        return self.duration

    @property
    def amount(self) -> float:
        """Convert cents to dollars for backwards compatibility."""
        return self.amount_cents / 100

    @property
    def qr_delivered_at(self) -> Optional[datetime]:
        """Check if QR was delivered based on esim_email_sent."""
        if self.esim_email_sent and self.esim_provisioned_at:
            return self.esim_provisioned_at
        return None

    def __repr__(self) -> str:
        return f"<Order {self.order_number} - {self.status.value}>"
