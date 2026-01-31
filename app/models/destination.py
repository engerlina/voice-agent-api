"""Destination database model - matches existing Prisma schema."""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Destination(Base):
    """Destination model - matches existing Prisma Destination table."""

    __tablename__ = "Destination"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    locale: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    tagline: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    country_iso: Mapped[Optional[str]] = mapped_column(String(2), index=True, nullable=True)
    region: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Timestamps
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updatedAt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    cities: Mapped[List["City"]] = relationship("City", back_populates="destination")

    def __repr__(self) -> str:
        return f"<Destination {self.slug} ({self.locale})>"


class City(Base):
    """City model - matches existing Prisma City table."""

    __tablename__ = "City"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    locale: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    country_iso: Mapped[str] = mapped_column(String(2), index=True, nullable=False)
    destination_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )

    # Unique content
    airport_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    airport_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    connectivity_notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # popular_areas stored as array in Postgres
    network_quality: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    timezone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    population: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Timestamps
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updatedAt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    destination: Mapped[Optional["Destination"]] = relationship(
        "Destination", back_populates="cities"
    )

    def __repr__(self) -> str:
        return f"<City {self.name} ({self.locale})>"
