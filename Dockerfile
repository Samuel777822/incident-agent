# Container entry point for the Agent Daemon web application
FROM python:3.11-slim

# Install system dependencies: Git and CA certificates for HTTPS git operations
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent application code
COPY . .

# Unbuffered output ensures real-time container log streaming
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV HOST=0.0.0.0

# Run the active hosted application, not a hard-coded sample customer daemon.
CMD ["python", "web_app.py"]
