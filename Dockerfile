FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Set environment defaults for read-only simulation mode
ENV AAROGYA_EXECUTION_MODE=SIMULATION \
    AAROGYA_LIVE_EXECUTION_ENABLED=false \
    AAROGYA_API_AUTH_ENABLED=true \
    GNANI_VOICE_PROVIDER_MODE=mock \
    PHARMACY_ENVIRONMENT=mock \
    PHARMACY_LIVE_OPERATIONS_ENABLED=false \
    PORT=8000

EXPOSE 8000

CMD ["sh", "-c", "uvicorn aarogya.api.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
