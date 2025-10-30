#!/bin/sh
set -e

# Ensure the appuser owns the /data directory.
# This is crucial for Docker volumes where the host UID/GID might not match.
echo "Taking ownership of /data directory..."
chown -R appuser:appuser /data

# If config.json doesn't exist, copy the example.
# This handles the case where a directory is created by Docker's volume mounting.
if [ ! -f "/app/config.json" ]; then
    echo "Config.json not found. Copying from example..."
    cp /app/app/config.json.example /app/config.json
    chown appuser:appuser /app/config.json
fi

# Execute the main command (passed as arguments to this script) as the 'appuser'
# 'gosu' is a lightweight tool for dropping privileges, safer than 'sudo'.
echo "Executing command as appuser: $@"
exec gosu appuser "$@"
