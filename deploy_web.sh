#!/bin/bash
set -e

# Configuration
USER="ubuntu"
INSTALL_DIR="/home/$USER/maxicourses-ovh/www/maxicourses_test"
SERVICE_DIR="/etc/systemd/system"

echo "🌐 Deploying Web Interface..."

cd "$INSTALL_DIR"

# 1. Create server_ovh.py
echo "  - Creating server_ovh.py..."
cp server.py server_ovh.py

# Add route for index_ovh.html
# We append it before "if __name__ == \"__main__\":"
# We use a temporary file to construct the new content
# Actually, server.py has @app.get("/") returning a string. We need to replace that.
# We will use python to modify it safely or sed.
# Let's use a simple sed to replace the home route.

sed -i 's|def home():|def home_api():|g' server_ovh.py
sed -i 's|@app.get("/")|@app.get("/api/home")|g' server_ovh.py

# Use python to insert routes before main block
cat <<EOF > patch_server.py
import sys

try:
    with open("server_ovh.py", "r") as f:
        lines = f.readlines()

    # Check if already patched to avoid duplication
    if any("def index_ovh():" in line for line in lines):
        print("Already patched.")
        sys.exit(0)

    new_lines = []
    inserted = False
    for line in lines:
        if "if __name__ == \"__main__\":" in line and not inserted:
            new_lines.append('@app.route("/")\n')
            new_lines.append('def index_ovh():\n')
            new_lines.append('    return send_from_directory("pipeline", "index_ovh.html")\n\n')
            new_lines.append('@app.route("/pipeline/<path:filename>")\n')
            new_lines.append('def serve_pipeline_files(filename):\n')
            new_lines.append('    return send_from_directory("pipeline", filename)\n\n')
            inserted = True
        new_lines.append(line)

    with open("server_ovh.py", "w") as f:
        f.writelines(new_lines)
    print("Patched server_ovh.py successfully.")
except Exception as e:
    print(f"Error patching: {e}")
    sys.exit(1)
EOF

python3 patch_server.py
rm patch_server.py

# 2. Create index_ovh.html
echo "  - Creating index_ovh.html..."
cp pipeline/index2.html pipeline/index_ovh.html

# Modify API Base
# Original: window.MAXICOURSES_API_BASE = 'http://127.0.0.1:5001';
# New: window.MAXICOURSES_API_BASE = '';
sed -i "s|window.MAXICOURSES_API_BASE = 'http://127.0.0.1:5001';|window.MAXICOURSES_API_BASE = '';|g" pipeline/index_ovh.html

# 3. Create Systemd Service
echo "  - Creating systemd service..."
cat <<EOF > maxicourses-web.service
[Unit]
Description=Maxicourses Web Interface
After=network.target

[Service]
User=$USER
WorkingDirectory=$INSTALL_DIR
Environment=PATH=$INSTALL_DIR/../.venv/bin:/usr/bin
ExecStart=$INSTALL_DIR/../.venv/bin/python3 server_ovh.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo mv maxicourses-web.service $SERVICE_DIR/
sudo systemctl daemon-reload
sudo systemctl enable --now maxicourses-web.service

echo "✅ Web Interface deployed and started!"
