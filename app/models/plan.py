"""Plan database model - matches Prisma schema."""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Plan(Base):
    """Plan model - matches Prisma Plan table.

    Each row represents pricing for a destination+locale+currency combination.
    The `durations` field contains all available plan durations with pricing.

    Prisma schema:
        model Plan {
            id                 Int       @id @default(autoincrement())
            destination_slug   String    @db.VarChar(50)
            locale             String    @db.VarChar(10)
            currency           String    @db.VarChar(3)
            best_daily_rate    Float?
            default_durations  Int[]
            durations          Json
            createdAt          DateTime  @default(now())
            updatedAt          DateTime  @updatedAt
        }
    """

    __tablename__ = "Plan"  # Prisma uses PascalCase

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    destination_slug: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    locale: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), index=True, nullable=False)
    best_daily_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    default_durations: Mapped[Optional[List[int]]] = mapped_column(ARRAY(Integer), nullable=True)
    durations: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Timestamps (Prisma uses camelCase)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def get_duration_plan(self, duration_days: int) -> Optional[dict]:
        """Get plan details for a specific duration."""
        if not self.durations:
            return None
        for plan in self.durations:
            if plan.get("duration") == duration_days:
                return plan
        return None

    def get_all_durations(self) -> List[dict]:
        """Get all duration plans."""
        return self.durations if self.durations else []

    def __repr__(self) -> str:
        return f"<Plan {self.destination_slug} ({self.currency})>"
