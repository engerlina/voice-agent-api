# Trvel FastAPI Dockerfile
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy all application code (needed for hatchling to find packages)
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir .

# Create non-root user
RUN adduser --disabled-password --gecos '' appuser && \
    chown -R appuser:appuser /app
USER appuser

# Expose port (Railway will assign dynamically via PORT env var)
EXPOSE ${PORT:-8000}

# Run the application (use PORT env var for Railway compatibility)
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
