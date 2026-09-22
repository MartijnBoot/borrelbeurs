#docker build -t bierbeurs:latest .
#docker save -o bierbeurs-image.tar bierbeurs:latest



# Dockerfile
FROM python:3.11-slim

# System setup (optional: faster/nicer logs)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install Python deps
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy app code
COPY . .

# Bake a template config outside any volume-mount path so it's always available
# as a fallback when the live config (mounted at /app/config/) is empty.
RUN cp config/exchange_config.json /app/default_exchange_config.json

# Ensure runtime dirs exist (your app writes here)
RUN mkdir -p static/earnings

EXPOSE 8000
CMD ["uvicorn", "backend.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
