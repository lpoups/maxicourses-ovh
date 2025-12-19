#!/bin/bash
# Test Course U collection via residential IP tunnel
# 
# USAGE:
#   ./test_courseu_tunnel.sh <EAN>
#
# PREREQUISITES:
# 1. Start Chrome debug on your LOCAL machine:
#    /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
#      --remote-debugging-port=9222 \
#      --user-data-dir=/tmp/chrome-debug-courseu
#
# 2. Create SSH tunnel from OVH to your local machine (reverse tunnel):
#    On your LOCAL machine, run:
#    ssh -R 9222:127.0.0.1:9222 ubuntu@vps-a4a36a41.vps.ovh.net -N
#
# This allows OVH server to access your local Chrome via the tunnel,
# using your residential IP instead of the OVH datacenter IP.

set -e

EAN="${1:-7613035833289}"  # Default: Perrier

cd "$(dirname "$0")"

echo "============================================"
echo "  Course U Tunnel Test"
echo "============================================"
echo ""
echo "EAN: $EAN"
echo "Testing connection to CDP port 9222 (residential tunnel)..."
echo ""

# Test if tunnel is active
if curl -s http://127.0.0.1:9222/json/version > /dev/null 2>&1; then
    echo "✅ CDP port 9222 is accessible!"
    CDP_INFO=$(curl -s http://127.0.0.1:9222/json/version | head -3)
    echo "$CDP_INFO"
else
    echo "❌ CDP port 9222 is NOT accessible!"
    echo ""
    echo "Please ensure:"
    echo "  1. Chrome is running with --remote-debugging-port=9222 on your LOCAL machine"
    echo "  2. SSH reverse tunnel is active: ssh -R 9222:127.0.0.1:9222 ubuntu@vps-a4a36a41.vps.ovh.net -N"
    exit 1
fi

echo ""
echo "Starting Course U collection..."
echo ""

# Run the collection with explicit tunnel port
export USE_CDP=1
export CDP_URL="http://127.0.0.1:9222"
export CDP_PORT_TUNNEL=9222
export DEBUG_COURSEU=1
export EAN="$EAN"

# Run the fetcher
python3 fetch_courseu_price.py

echo ""
echo "============================================"
echo "  Test Complete"
echo "============================================"
