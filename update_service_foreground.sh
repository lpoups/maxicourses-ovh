#!/bin/bash
set -e

SERVICE_FILE="/etc/systemd/system/chrome-debug@.service"
NEW_SCRIPT="/home/ubuntu/maxicourses-ovh/www/maxicourses_test/start_chrome_foreground.sh"

echo "🔧 Updating systemd service to use foreground script..."

# 1. Update ExecStart
sudo sed -i "s|ExecStart=.*|ExecStart=$NEW_SCRIPT|g" $SERVICE_FILE

# 2. Revert Type to simple
sudo sed -i "s/Type=forking/Type=simple/g" $SERVICE_FILE

# 3. Kill existing chrome
echo "🔪 Killing existing chrome processes..."
pkill -f chrome || true
pkill -f xvfb || true

# 4. Reload and restart
sudo systemctl daemon-reload
sudo systemctl restart chrome-debug@ubuntu.service

echo "✅ Service updated and restarted."
