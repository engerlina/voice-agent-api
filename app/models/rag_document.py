"""Document and RAG models."""

import enum
import uuid
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TenantMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.tenant import Tenant


class DocumentStatus(str, enum.Enum):
    """Document processing status."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DocumentType(str, enum.Enum):
    """Document types."""

    PDF = "pdf"
    TXT = "txt"
    DOCX = "docx"
    URL = "url"
    MANUAL = "manual"


class Document(Base, TimestampMixin, TenantMixin):
    """Document for RAG knowledge base."""

    __tablename__ = "documents"

    # Document info
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    doc_type: Mapped[DocumentType] = mapped_column(Enum(DocumentType), nullable=False)

    # Source
    source_url: Mapped[str | None] = mapped_column(String(1000))
    file_path: Mapped[str | None] = mapped_column(String(1000))
    file_size_bytes: Mapped[int | None] = mapped_column(Integer)

    # Processing
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus),
        default=DocumentStatus.PENDING,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)

    # Metadata
    extra_data: Mapped[dict | None] = mapped_column("metadata", JSON)

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="documents")
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan",
    )


class DocumentChunk(Base, TimestampMixin):
    """Document chunk with embedding for vector search."""

    __tablename__ = "document_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Content
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # Embedding (1536 dimensions for OpenAI text-embedding-3-small)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))

    # Metadata
    extra_data: Mapped[dict | None] = mapped_column("metadata", JSON)
    token_count: Mapped[int | None] = mapped_column(Integer)

    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="chunks")
