"""Customer database model - matches Prisma schema."""

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.order import Order


class Customer(Base):
    """Customer model - matches Prisma schema exactly.

    Prisma schema:
        model Customer {
            id                 Int      @id @default(autoincrement())
            email              String   @unique @db.VarChar(255)
            name               String?  @db.VarChar(200)
            phone              String?  @db.VarChar(50)
            stripe_customer_id String?  @unique @db.VarChar(100)
            createdAt          DateTime @default(now())
            updatedAt          DateTime @updatedAt
        }
    """

    __tablename__ = "Customer"  # Prisma uses PascalCase table names

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(
        String(100), unique=True, nullable=True
    )

    # Prisma uses camelCase for timestamps
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    orders: Mapped[List["Order"]] = relationship("Order", back_populates="customer")

    @property
    def first_name(self) -> Optional[str]:
        """Extract first name from name field for backwards compatibility."""
        if self.name:
            parts = self.name.split(" ", 1)
            return parts[0] if parts else None
        return None

    @property
    def last_name(self) -> Optional[str]:
        """Extract last name from name field for backwards compatibility."""
        if self.name:
            parts = self.name.split(" ", 1)
            return parts[1] if len(parts) > 1 else None
        return None

    def __repr__(self) -> str:
        return f"<Customer {self.email}>"
