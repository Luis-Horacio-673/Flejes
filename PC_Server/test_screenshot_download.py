import subprocess
import urllib.request
import json
import ssl
import sys
import os
from datetime import datetime

# Set stdout to UTF-8
sys.stdout.reconfigure(encoding='utf-8')

sn = "25816A000001193"
ip = "192.168.41.1"
base_url = f"https://{ip}:16674"
ssl_context = ssl._create_unverified_context()

# Load configuration if available
watch_dir = None
if len(sys.argv) > 1:
    watch_dir = sys.argv[1]
    config_path = os.path.join(watch_dir, "config.json")
else:
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

if os.path.exists(config_path):
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            if "ip" in config:
                ip = config["ip"]
                base_url = f"https://{ip}:16674"
            if "sn" in config:
                sn = config["sn"]
            if "watch_dir" in config and watch_dir is None:
                watch_dir = config["watch_dir"]
    except Exception as e:
        print(f"Warning: Failed to load config.json: {e}")

# 1. Login
login_payload = {
    "sn": sn,
    "username": "admin",
    "password": "SN2008@+",
    "clientId": "ff4a5aa7-da81-46bd-a1c0-fee4aa11fba0",
    "clientName": "NC000069",
    "loginType": 9,
    "source": {"type": 0, "platform": 2, "platformVersion": "4.0.1"}
}

print("Logging in...")
try:
    req_data = json.dumps(login_payload).encode('utf-8')
    req = urllib.request.Request(f"{base_url}/terminal/core/v1/login", data=req_data, headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req, context=ssl_context, timeout=5) as r:
        body = json.loads(r.read().decode('utf-8'))
        token = body['data']['token']
        print(f"Login success! Token: {token}")
except Exception as e:
    print("Login failed:", e)
    sys.exit(1)

# 2. Trigger screenshot via PUT
# We use type 'default' which returned successfully earlier.
print("\nRequesting screenshot generation...")
payload = {
    "width": 1440,
    "height": 32,
    "type": "default"
}
payload_str = json.dumps(payload)

curl_trigger = [
    "curl", "-k", "-s",
    "-X", "PUT",
    "-H", f"Authorization: {token}",
    "-H", "Content-Type: application/json",
    "-d", payload_str,
    f"{base_url}/terminal/core/v1/screen/shot/get"
]

res_trigger = subprocess.run(curl_trigger, capture_output=True)
res_text = res_trigger.stdout.decode('utf-8', errors='ignore')
print("Trigger response:", res_text)

try:
    trigger_json = json.loads(res_text)
    if trigger_json.get('code') != 0:
        print("Error triggering screenshot:", trigger_json.get('message'))
        sys.exit(1)
        
    remote_path = trigger_json['data']['path']
    print(f"Screenshot generated successfully on device at: {remote_path}")
    
except Exception as e:
    print("Failed to parse trigger response:", e)
    sys.exit(1)

# 3. Download the generated screenshot file
# URL: /terminal/tools/v1/file/download?filePath=<remote_path>
print("\nDownloading screenshot from TB10 Plus...")
# Quote the remote path just in case
download_url = f"{base_url}/terminal/tools/v1/file/download?filePath={urllib.parse.quote(remote_path)}"

curl_download = [
    "curl", "-k", "-s",
    "-X", "GET",
    "-H", f"Authorization: {token}",
    download_url
]

res_download = subprocess.run(curl_download, capture_output=True)
image_bytes = res_download.stdout

print(f"Downloaded {len(image_bytes)} bytes.")

if len(image_bytes) > 0:
    # Auto-detect extension
    ext = ".png"
    if image_bytes.startswith(b'\x89PNG'):
        ext = ".png"
    elif image_bytes.startswith(b'\xff\xd8'):
        ext = ".jpg"
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = watch_dir if watch_dir else script_dir
    dest_dir = os.path.join(base_dir, "procesados")
    os.makedirs(dest_dir, exist_ok=True)
    save_path = os.path.join(dest_dir, f"pantalla_en_vivo_{timestamp}{ext}")
    
    with open(save_path, 'wb') as f:
        f.write(image_bytes)
        
    print(f"\n=======================================================")
    print("=== ¡CAPTURA DE PANTALLA OBTENIDA CON ÉXITO! ===")
    print(f" Guardada localmente como: {save_path}")
    print("=======================================================")
else:
    print("Downloaded file was empty.")
