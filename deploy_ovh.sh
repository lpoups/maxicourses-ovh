#!/bin/bash
set -e

# Configuration
REMOTE_HOST="ovh-server"
REMOTE_USER="ubuntu"
REMOTE_DIR="~/maxicourses-ovh"
LOCAL_DIR="$(pwd)"

echo "🚀 Starting deployment to $REMOTE_HOST..."

# 1. Create remote directory
echo "📂 Creating remote directory..."
ssh $REMOTE_HOST "mkdir -p $REMOTE_DIR"

# 2. Sync files
echo "🔄 Syncing files..."
rsync -avz --delete \
    --exclude '.git' \
    --exclude '.venv' \
    --exclude 'node_modules' \
    --exclude '.vscode' \
    --exclude '__pycache__' \
    --exclude '.DS_Store' \
    --exclude 'tmp' \
    --exclude 'logs' \
    --exclude 'traces' \
    --exclude 'poc_runs' \
    --exclude '.chrome-*' \
    --exclude 'maxicourses_local' \
    --exclude 'www/maxicourses_test/results' \
    --exclude 'www/maxicourses_test/state' \
    --exclude 'www/maxicourses_test/assets' \
    --exclude '.env' \
    --exclude 'mongo_data' \
    "$LOCAL_DIR/" "$REMOTE_HOST:$REMOTE_DIR/"

# 3. Setup Remote Environment
echo "🐍 Setting up remote environment..."
ssh $REMOTE_HOST << EOF
    cd $REMOTE_DIR/www
    if [ ! -d ".venv" ]; then
        echo "Creating virtual environment..."
        python3 -m venv .venv
    fi
    source .venv/bin/activate
    
    echo "📦 Installing dependencies..."
    if [ -f "maxicourses_test/requirements.txt" ]; then
        pip install -r maxicourses_test/requirements.txt
    else
        echo "⚠️ Warning: maxicourses_test/requirements.txt not found!"
    fi
    
    # Install playwright browsers if needed (check if already installed to save time?)
    # For now, just ensure it's installed.
    echo "🎭 Installing Playwright browsers..."
    playwright install chromium
    
    echo "♻️ Restarting Web Service..."
    sudo systemctl restart maxicourses-web
EOF

echo "✅ Deployment completed successfully!"
