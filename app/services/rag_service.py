"""RAG (Retrieval Augmented Generation) service using Pinecone."""

import uuid
from typing import Any

from openai import AsyncOpenAI
from pinecone import Pinecone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger

# Import from new document model (user-scoped)
try:
    from app.models.document import Document, DocumentStatus
except ImportError:
    # Fallback to rag_document if document.py doesn't exist
    from app.models.rag_document import Document, DocumentStatus

logger = get_logger(__name__)

# Initialize Pinecone client (singleton)
_pinecone_client: Pinecone | None = None
_pinecone_index = None


def get_pinecone_index():
    """Get or create Pinecone index connection."""
    global _pinecone_client, _pinecone_index

    if _pinecone_index is None:
        if not settings.pinecone_api_key or not settings.pinecone_url:
            raise ValueError("Pinecone API key and URL must be configured")

        _pinecone_client = Pinecone(api_key=settings.pinecone_api_key)

        # Extract host from URL (remove https://)
        host = settings.pinecone_url.replace("https://", "").replace("http://", "")
        _pinecone_index = _pinecone_client.Index(host=host)

        logger.info("Pinecone index connected", host=host)

    return _pinecone_index


class RAGService:
    """Service for document processing and retrieval using Pinecone."""

    # text-embedding-3-large produces 3072 dimensions
    EMBEDDING_DIMENSIONS = 3072

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.openai = AsyncOpenAI(api_key=settings.openai_api_key)
        self.embedding_model = settings.openai_embedding_model
        self.index = get_pinecone_index()

    async def generate_embedding(self, text: str) -> list[float]:
        """Generate embedding vector for text using OpenAI text-embedding-3-large."""
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
        """Process document: chunk, embed, and store in Pinecone with user namespace."""
        # Get document
        result = await self.db.execute(
            select(Document).where(Document.id == document_id)
        )
        document = result.scalar_one_or_none()

        if not document:
            raise ValueError(f"Document not found: {document_id}")

        # Use user_id as namespace for multi-user isolation
        # (supports both user_id and tenant_id for backwards compatibility)
        namespace = str(getattr(document, "user_id", None) or getattr(document, "tenant_id", document_id))

        try:
            document.status = DocumentStatus.PROCESSING
            await self.db.commit()

            # Chunk the content
            chunks = self._chunk_text(content, chunk_size, chunk_overlap)
            logger.info(
                "Document chunked",
                document_id=str(document_id),
                tenant_id=namespace,
                chunk_count=len(chunks),
            )

            # Generate embeddings and prepare vectors for Pinecone
            vectors = []
            for i, chunk_text in enumerate(chunks):
                embedding = await self.generate_embedding(chunk_text)

                vector_id = f"{document_id}_{i}"
                vectors.append({
                    "id": vector_id,
                    "values": embedding,
                    "metadata": {
                        "document_id": str(document_id),
                        "document_name": document.name,
                        "chunk_index": i,
                        "content": chunk_text[:8000],  # Pinecone metadata limit
                        "token_count": len(chunk_text.split()),
                    },
                })

            # Upsert to Pinecone in batches of 100
            batch_size = 100
            for i in range(0, len(vectors), batch_size):
                batch = vectors[i : i + batch_size]
                self.index.upsert(vectors=batch, namespace=namespace)

            document.chunk_count = len(chunks)
            document.status = DocumentStatus.COMPLETED
            await self.db.commit()

            logger.info(
                "Document processing completed",
                document_id=str(document_id),
                tenant_id=namespace,
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

    async def delete_document(self, document_id: uuid.UUID, user_id: str) -> None:
        """Delete all vectors for a document from Pinecone."""
        namespace = str(user_id)

        # Delete by filter on document_id metadata
        self.index.delete(
            filter={"document_id": {"$eq": str(document_id)}},
            namespace=namespace,
        )

        logger.info(
            "Document vectors deleted",
            document_id=str(document_id),
            tenant_id=namespace,
        )

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
        user_id: str,
        query: str,
        top_k: int = 5,
        similarity_threshold: float = 0.7,
    ) -> list[dict[str, Any]]:
        """Search documents using Pinecone vector similarity within user namespace."""
        namespace = str(user_id)

        # Generate query embedding
        query_embedding = await self.generate_embedding(query)

        # Query Pinecone
        results = self.index.query(
            vector=query_embedding,
            top_k=top_k,
            namespace=namespace,
            include_metadata=True,
        )

        # Filter by similarity threshold and format results
        filtered_results = []
        for match in results.matches:
            # Pinecone returns similarity score (higher is better, 0-1 for cosine)
            if match.score >= similarity_threshold:
                metadata = match.metadata or {}
                filtered_results.append({
                    "chunk_id": match.id,
                    "document_id": metadata.get("document_id"),
                    "document_name": metadata.get("document_name", "Unknown"),
                    "content": metadata.get("content", ""),
                    "chunk_index": metadata.get("chunk_index", 0),
                    "similarity": match.score,
                })

        logger.info(
            "RAG search completed",
            tenant_id=namespace,
            query_preview=query[:50],
            results_count=len(filtered_results),
        )

        return filtered_results

    async def get_context_for_query(
        self,
        user_id: str,
        query: str,
        top_k: int = 5,
        max_tokens: int = 2000,
    ) -> str:
        """Get relevant context for a query, formatted for LLM."""
        results = await self.search(user_id, query, top_k=top_k)

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

            context_parts.append(f"[Source: {result['document_name']}]\n{content}")
            total_tokens += tokens

        return "\n\n---\n\n".join(context_parts)


async def get_rag_service(db: AsyncSession) -> RAGService:
    """Get RAG service instance."""
    return RAGService(db)
