#!/bin/bash
set -e

# Configuration
USER="ubuntu"
INSTALL_DIR="/home/$USER/maxicourses-ovh"
SERVICE_DIR="/etc/systemd/system"

echo "🔧 Configuring systemd services..."

cd "$INSTALL_DIR/www/infra/ovh"

# 1. Chrome Debug Service
echo "  - Configuring chrome-debug@.service"
# Replace WorkingDirectory and ExecStart paths
# Original: /home/%i/Sites/maxicourses-ovh/...
# New: /home/ubuntu/maxicourses-ovh/...
# Since we use @.service, %i will be the user.
# If we run as chrome-debug@ubuntu, %i = ubuntu.
# The path in the file is /home/%i/Sites/maxicourses-ovh...
# We need to change it to /home/%i/maxicourses-ovh... (remove Sites)
sed "s|Sites/maxicourses-ovh|maxicourses-ovh|g" chrome-debug@.service > chrome-debug-custom@.service

sudo cp chrome-debug-custom@.service $SERVICE_DIR/chrome-debug@.service

# 2. Run Pipeline Service
echo "  - Configuring run-pipeline@.service"
# Replace User=maxi with User=ubuntu
# Replace paths
sed "s|User=maxi|User=$USER|g" run-pipeline@.service > run-pipeline-custom@.service
sed -i "s|/home/maxi/Sites/maxicourses-ovh|/home/$USER/maxicourses-ovh|g" run-pipeline-custom@.service
# Also need to fix the dependency on chrome-debug
sed -i "s|chrome-debug@maxi.service|chrome-debug@$USER.service|g" run-pipeline-custom@.service

sudo cp run-pipeline-custom@.service $SERVICE_DIR/run-pipeline@.service

# 3. Run Pipeline Timer
echo "  - Configuring run-pipeline@.timer"
sudo cp run-pipeline@.timer $SERVICE_DIR/

# 4. Reload and Enable
echo "🔄 Reloading systemd..."
sudo systemctl daemon-reload

echo "🚀 Starting Chrome Debug Service for $USER..."
sudo systemctl enable --now chrome-debug@$USER.service

echo "✅ Services configured successfully!"
