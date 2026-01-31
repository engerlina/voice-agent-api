"""RAG (Retrieval Augmented Generation) service."""

import uuid
from typing import Any

from openai import AsyncOpenAI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.document import Document, DocumentChunk, DocumentStatus

logger = get_logger(__name__)


class RAGService:
    """Service for document processing and retrieval."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.openai = AsyncOpenAI(api_key=settings.openai_api_key)
        self.embedding_model = settings.openai_embedding_model

    async def generate_embedding(self, text: str) -> list[float]:
        """Generate embedding vector for text."""
        response = await self.openai.embeddings.create(
            model=self.embedding_model,
            input=text,
        )
        return response.data[0].embedding

    async def process_document(
        self,
        document_id: uuid.UUID,
        content: str,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ) -> int:
        """Process document: chunk and generate embeddings."""
        # Get document
        result = await self.db.execute(
            select(Document).where(Document.id == document_id)
        )
        document = result.scalar_one_or_none()

        if not document:
            raise ValueError(f"Document not found: {document_id}")

        try:
            document.status = DocumentStatus.PROCESSING
            await self.db.commit()

            # Chunk the content
            chunks = self._chunk_text(content, chunk_size, chunk_overlap)
            logger.info(
                "Document chunked",
                document_id=str(document_id),
                chunk_count=len(chunks),
            )

            # Generate embeddings and store chunks
            for i, chunk_text in enumerate(chunks):
                embedding = await self.generate_embedding(chunk_text)

                chunk = DocumentChunk(
                    document_id=document_id,
                    content=chunk_text,
                    chunk_index=i,
                    embedding=embedding,
                    token_count=len(chunk_text.split()),  # Rough estimate
                )
                self.db.add(chunk)

            document.chunk_count = len(chunks)
            document.status = DocumentStatus.COMPLETED
            await self.db.commit()

            logger.info(
                "Document processing completed",
                document_id=str(document_id),
                chunk_count=len(chunks),
            )
            return len(chunks)

        except Exception as e:
            document.status = DocumentStatus.FAILED
            document.error_message = str(e)
            await self.db.commit()
            logger.error(
                "Document processing failed",
                document_id=str(document_id),
                error=str(e),
            )
            raise

    def _chunk_text(
        self,
        text: str,
        chunk_size: int,
        overlap: int,
    ) -> list[str]:
        """Split text into overlapping chunks."""
        chunks = []
        start = 0

        while start < len(text):
            end = start + chunk_size

            # Try to break at sentence boundary
            if end < len(text):
                # Look for sentence ending within last 100 chars
                for i in range(min(100, end - start)):
                    if text[end - i] in ".!?\n":
                        end = end - i + 1
                        break

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            start = end - overlap

        return chunks

    async def search(
        self,
        tenant_id: uuid.UUID,
        query: str,
        top_k: int = 5,
        similarity_threshold: float = 0.7,
    ) -> list[dict[str, Any]]:
        """Search documents using vector similarity."""
        # Generate query embedding
        query_embedding = await self.generate_embedding(query)

        # Use pgvector for similarity search
        # The <=> operator computes cosine distance (1 - cosine_similarity)
        sql = text("""
            SELECT
                dc.id,
                dc.document_id,
                dc.content,
                dc.chunk_index,
                d.name as document_name,
                1 - (dc.embedding <=> :query_embedding::vector) as similarity
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE d.tenant_id = :tenant_id
              AND d.status = 'completed'
              AND 1 - (dc.embedding <=> :query_embedding::vector) >= :threshold
            ORDER BY dc.embedding <=> :query_embedding::vector
            LIMIT :top_k
        """)

        result = await self.db.execute(
            sql,
            {
                "query_embedding": query_embedding,
                "tenant_id": tenant_id,
                "threshold": similarity_threshold,
                "top_k": top_k,
            },
        )

        rows = result.fetchall()

        return [
            {
                "chunk_id": row.id,
                "document_id": row.document_id,
                "document_name": row.document_name,
                "content": row.content,
                "chunk_index": row.chunk_index,
                "similarity": row.similarity,
            }
            for row in rows
        ]

    async def get_context_for_query(
        self,
        tenant_id: uuid.UUID,
        query: str,
        top_k: int = 5,
        max_tokens: int = 2000,
    ) -> str:
        """Get relevant context for a query, formatted for LLM."""
        results = await self.search(tenant_id, query, top_k=top_k)

        if not results:
            return ""

        # Build context string
        context_parts = []
        total_tokens = 0

        for result in results:
            content = result["content"]
            tokens = len(content.split())  # Rough estimate

            if total_tokens + tokens > max_tokens:
                break

            context_parts.append(
                f"[Source: {result['document_name']}]\n{content}"
            )
            total_tokens += tokens

        return "\n\n---\n\n".join(context_parts)


async def get_rag_service(db: AsyncSession) -> RAGService:
    """Get RAG service instance."""
    return RAGService(db)
