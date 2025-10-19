# Use a Python 3.11 slim base image compatible with ARM64 and x86_64
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=America/Sao_Paulo

# Install system dependencies
# - ffmpeg: for video and audio processing
# - git: for pulling dependencies if needed (good practice)
# - tini: a minimal init system for containers
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    tini \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create a non-root user to run the application
RUN useradd --system --create-home appuser
RUN chown -R appuser:appuser /app

# Copy the application code into the container
COPY . .
RUN chown -R appuser:appuser /app

# Switch to the non-root user
USER appuser

# Expose the port the web UI will run on
EXPOSE 8080

# Healthcheck to verify the application is running
# This calls the internal validation command, which is a good check.
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD ["python", "-m", "app.main", "validate"]

# Set tini as the entrypoint to handle signals properly
ENTRYPOINT ["/usr/bin/tini", "--"]

# Default command to run the web server
# The port can be overridden by the UI_PORT environment variable.
CMD ["python", "-m", "app.main", "serve", "--host", "0.0.0.0"]
