#!/bin/bash
echo "Configuring sudoers for maxicourses control panel..."

# Create sudoers file content
SUDOERS_CONTENT="ubuntu ALL=(ALL) NOPASSWD: /usr/bin/systemctl status maxicourses-web.service
ubuntu ALL=(ALL) NOPASSWD: /usr/bin/systemctl start maxicourses-web.service
ubuntu ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart maxicourses-web.service
ubuntu ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop maxicourses-web.service
ubuntu ALL=(ALL) NOPASSWD: /usr/bin/journalctl -u maxicourses-web.service*
ubuntu ALL=(ALL) NOPASSWD: /usr/bin/systemctl status chrome-debug@ubuntu.service
ubuntu ALL=(ALL) NOPASSWD: /usr/bin/systemctl start chrome-debug@ubuntu.service
ubuntu ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart chrome-debug@ubuntu.service
ubuntu ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop chrome-debug@ubuntu.service
ubuntu ALL=(ALL) NOPASSWD: /usr/bin/kill *
"

# Write to a temporary file first
echo "$SUDOERS_CONTENT" > /tmp/maxicourses_sudoers

# Move to /etc/sudoers.d/ with correct permissions
sudo mv /tmp/maxicourses_sudoers /etc/sudoers.d/maxicourses
sudo chmod 0440 /etc/sudoers.d/maxicourses
sudo chown root:root /etc/sudoers.d/maxicourses

echo "✅ Sudoers configuration updated."
