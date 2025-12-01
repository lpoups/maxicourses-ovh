#!/bin/bash
set -e

# Patch server_ovh.py to add assets route
cat <<EOF > patch_assets.py
import sys

try:
    with open("server_ovh.py", "r") as f:
        lines = f.readlines()

    # Check if already patched
    if any("def serve_assets(filename):" in line for line in lines):
        print("Assets route already exists.")
        sys.exit(0)

    new_lines = []
    inserted = False
    for line in lines:
        if "if __name__ == \"__main__\":" in line and not inserted:
            new_lines.append('@app.route("/assets/<path:filename>")\n')
            new_lines.append('def serve_assets(filename):\n')
            new_lines.append('    return send_from_directory("assets", filename)\n\n')
            inserted = True
        new_lines.append(line)

    with open("server_ovh.py", "w") as f:
        f.writelines(new_lines)
    print("Patched server_ovh.py with assets route.")
except Exception as e:
    print(f"Error patching: {e}")
    sys.exit(1)
EOF

python3 patch_assets.py
rm patch_assets.py

# Restart service
sudo systemctl restart maxicourses-web.service
echo "Service restarted."
