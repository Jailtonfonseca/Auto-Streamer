#!/bin/sh
set -e

# Ensure the appuser owns the /data directory.
# This is crucial for Docker volumes where the host UID/GID might not match.
echo "Taking ownership of /data directory..."
chown -R appuser:appuser /data

# Execute the main command (passed as arguments to this script) as the 'appuser'
# 'gosu' is a lightweight tool for dropping privileges, safer than 'sudo'.
echo "Executing command as appuser: $@"
exec gosu appuser "$@"
