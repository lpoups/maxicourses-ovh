#!/bin/bash
set -e

DOMAIN="api.maxicourses.fr"
PORT=5001

echo "🛠️ Installing Nginx and Certbot..."
sudo apt-get update
sudo apt-get install -y nginx certbot python3-certbot-nginx

echo "⚙️ Configuring Nginx for $DOMAIN..."

# Create Nginx config
cat <<EOF | sudo tee /etc/nginx/sites-available/maxicourses
server {
    listen 80;
    server_name $DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

# Enable site
sudo ln -sf /etc/nginx/sites-available/maxicourses /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Test config
sudo nginx -t

# Reload Nginx
sudo systemctl reload nginx

echo "✅ Nginx configured (HTTP only for now). Waiting for DNS to run Certbot."
