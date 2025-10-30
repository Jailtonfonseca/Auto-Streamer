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
# - gosu: a lightweight tool for dropping root privileges
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    gosu \
    tini \
    fonts-dejavu-core \
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

# Copy the entrypoint script and make it executable
COPY entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh

# Set the entrypoint to our custom script
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# Default command to run the web server
# This command is passed to the entrypoint script
CMD ["python", "-m", "app.main", "serve", "--host", "0.0.0.0"]
