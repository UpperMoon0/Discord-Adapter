# Lily-Discord-Adapter Dockerfile
# Discord bot adapter for Lily-Core

# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsodium-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file
COPY requirements.txt .

# Install Python dependencies
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . /app/Lily-Discord-Adapter

# Set working directory to the application directory
WORKDIR /app/Lily-Discord-Adapter

# Make yt-dlp binary executable
RUN chmod +x /app/Lily-Discord-Adapter/yt-dlp

# Add current directory to Python path
ENV PYTHONPATH=/app/Lily-Discord-Adapter

# Expose the port the app runs on (for health checks and metrics)
EXPOSE 8004

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8004/health', timeout=5)" || exit 1

# Run the bot
CMD ["python", "main.py"]
