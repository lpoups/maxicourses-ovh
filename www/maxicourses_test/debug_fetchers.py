import subprocess
import os
import sys
import json

EAN = "4009900540865"
ENV = os.environ.copy()
ENV["EAN"] = EAN
ENV["HEADLESS"] = "1"

SCRIPTS = [
    ("auchan", "fetch_auchan_price.py"),
    ("courseu", "fetch_courseu_price.py"),
    ("carrefour_market", "fetch_carrefour_price.py"), # Will set STORE_QUERY
    ("chronodrive", "fetch_chronodrive_price.py"),
    ("intermarche", "fetch_intermarche_price.py"),
    ("casino", "fetch_casino_price.py"),
]

def run_script(name, script):
    print(f"--- Testing {name} ({script}) ---")
    local_env = ENV.copy()
    if name == "carrefour_market":
        local_env["STORE_QUERY"] = "Carrefour Market"
        local_env["CARREFOUR_FRONTAL_STORE"] = "" # Clear specific store ID to force search
    
    cmd = [sys.executable, script]
    try:
        res = subprocess.run(cmd, env=local_env, capture_output=True, text=True, timeout=60)
        print(f"Return Code: {res.returncode}")
        if res.stdout:
            try:
                data = json.loads(res.stdout)
                print("JSON Output:", json.dumps(data, indent=2, ensure_ascii=False))
            except:
                print("Raw Stdout:", res.stdout[:500] + "...")
        if res.stderr:
            print("Stderr:", res.stderr[-500:])
    except subprocess.TimeoutExpired:
        print("TIMEOUT")
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    for name, script in SCRIPTS:
        if os.path.exists(script):
            run_script(name, script)
        else:
            print(f"Script missing: {script}")
