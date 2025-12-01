#!/bin/bash
set -e

cd ~/maxicourses-ovh/www
source .venv/bin/activate

export USE_CDP=1
export CDP_URL="http://127.0.0.1:9222"

echo "🧪 Running verification test..."
# Check if we can import modules and connect to CDP
python3 -c "
import sys
import os
sys.path.append(os.getcwd())
sys.path.append(os.path.join(os.getcwd(), 'maxicourses_test'))
try:
    import maxicourses_test.manual_leclerc_cdp
    print('✅ Module import successful')
except ImportError as e:
    print(f'❌ Import failed: {e}')
    sys.exit(1)
"

# Try a simple curl to CDP again to be sure from within the env context (though env doesn't change network)
curl -s $CDP_URL/json/version > /dev/null && echo "✅ CDP connection verified" || echo "❌ CDP connection failed"

echo "✅ Verification complete."
