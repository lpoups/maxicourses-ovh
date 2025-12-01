#!/bin/bash
set -e

SERVICE_FILE="/etc/systemd/system/chrome-debug@.service"

echo "🔧 Fixing systemd service type..."

# Change Type=simple to Type=forking
sudo sed -i "s/Type=simple/Type=forking/g" $SERVICE_FILE

# Reload and restart
sudo systemctl daemon-reload
sudo systemctl restart chrome-debug@ubuntu.service

echo "✅ Service updated and restarted."
