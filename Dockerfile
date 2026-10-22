# Container entry point for the Agent Daemon web application
FROM python:3.13-slim

# CA certificates are needed for the GitHub and Groq HTTPS APIs.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
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

# Run a production WSGI server. Render injects PORT at runtime.
CMD ["python", "run_portal.py"]

