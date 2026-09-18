import subprocess
import json
import urllib.parse
import os
import sys
import base64
import time

# Set stdout to UTF-8
sys.stdout.reconfigure(encoding='utf-8')

sn = "25816A000001193"
ip = "192.168.41.1"
base_url = f"https://{ip}:16674"

# Load configuration if available
if len(sys.argv) > 2:
    watch_dir = sys.argv[2]
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
    except Exception as e:
        print(f"Warning: Failed to load config.json: {e}")

def run_curl(url, method='GET', headers=None, data_json=None, data_binary_file=None):
    # Force HTTP/1.1 to prevent connection resets on large transfers with embedded AndServer
    cmd = ["curl", "-k", "-sS", "--http1.1", "-X", method]
    if headers:
        for k, v in headers.items():
            cmd.extend(["-H", f"{k}: {v}"])
    
    if data_json:
        cmd.extend(["-d", json.dumps(data_json)])
    elif data_binary_file:
        # Use -T (upload-file) for native chunked PUT uploads which is more stable than --data-binary
        cmd.extend(["-T", data_binary_file])
        
    cmd.append(url)
    
    res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
    if res.returncode != 0:
        raise Exception(f"curl error: {res.stderr}")
    
    try:
        return json.loads(res.stdout)
    except:
        return res.stdout

def publish_nova_folder(nova_dir):
    print(f"--- Starting Publish Process for: {nova_dir} ---")
    
    # 1. Read and decode command.json
    cmd_path = os.path.join(nova_dir, "command.json")
    if not os.path.exists(cmd_path):
        print(f"Error: {cmd_path} not found!")
        return False
        
    with open(cmd_path, 'r', encoding='utf-8') as f:
        cmd_b64 = f.read().strip()
        
    cmd_json_str = base64.b64decode(cmd_b64).decode('utf-8')
    cmd_data = json.loads(cmd_json_str)
    
    if not cmd_data.get("programInfos"):
        print("Error: No programInfos found in command.json")
        return False
        
    prog_info = cmd_data["programInfos"][0]
    prog_name = prog_info["name"]
    prog_url = prog_info["url"]
    prog_identifier = prog_info["identifier"]
    prog_size = prog_info["size"]
    thumbnail_name = prog_info["thumbnailName"]
    
    print(f"Program Name: {prog_name}")
    print(f"Program Folder Name: {prog_url}")
    print(f"Identifier: {prog_identifier}")
    print(f"Size: {prog_size} bytes")
    
    # 2. Read planlist.json and playlist0.json
    prog_dir = os.path.join(nova_dir, "program", prog_url)
    planlist_path = os.path.join(prog_dir, "planlist.json")
    playlist_path = os.path.join(prog_dir, "playlist0.json")
    
    if not os.path.exists(planlist_path) or not os.path.exists(playlist_path):
        print("Error: planlist.json or playlist0.json not found in program folder!")
        return False
        
    with open(planlist_path, 'r', encoding='utf-8') as f:
        plan_data = json.load(f)
        
    with open(playlist_path, 'r', encoding='utf-8') as f:
        play_data = json.load(f)
        
    prog_uuid = play_data["uuid"]
    width = play_data["width"]
    height = play_data["height"]
    
    # Calculate duration
    duration = 0
    if play_data.get("sceneItems"):
        for item in play_data["sceneItems"]:
            duration += item.get("duration", 0)
    if duration == 0:
        duration = 10000  # default 10 seconds
        
    print(f"UUID: {prog_uuid}")
    print(f"Dimensions: {width}x{height} px")
    print(f"Duration: {duration} ms")
    
    # 3. Log in to get token
    print("\nLogging in to Taurus module...")
    login_payload = {
        "sn": sn,
        "username": "admin",
        "password": "SN2008@+",
        "clientId": "ff4a5aa7-da81-46bd-a1c0-fee4aa11fba0",
        "clientName": "NC000069",
        "loginType": 9,
        "source": {"type": 0, "platform": 2, "platformVersion": "4.0.1"}
    }
    
    login_res = run_curl(f"{base_url}/terminal/core/v1/login", "POST", {'Content-Type': 'application/json'}, data_json=login_payload)
    if not isinstance(login_res, dict) or 'data' not in login_res or 'token' not in login_res['data']:
        print("Login failed:", login_res)
        return False
        
    token = login_res['data']['token']
    print(f"Login success! Token: {token}")
    
    # 4. Prepare Media Files list
    resources = plan_data.get("resources", [])
    check_files = []
    file_size_infos = []
    total_media_size = 0
    
    for r in resources:
        res_name = r["fileName"]
        res_size = r["size"]
        check_files.append(res_name)
        file_size_infos.append({"name": res_name, "size": res_size})
        total_media_size += res_size
        
    # 5. Start Transfer
    print("\nStarting transfer on device...")
    start_payload = {
        "deviceIdentifier": "NC000069",
        "totalSize": prog_size,
        "type": "DEFAULT",
        "local": False,
        "source": 0,
        "solutions": {
            "name": prog_name,
            "identifier": prog_identifier
        },
        "checkFiles": check_files,
        "totalMediaSize": total_media_size,
        "judgeForDevice": True,
        "fileSizeInfos": file_size_infos
    }
    
    start_res = run_curl(
        f"{base_url}/terminal/core/v1/play/transfer/start", 
        "PUT", 
        {'Content-Type': 'application/json', 'Authorization': token}, 
        data_json=start_payload
    )
    
    if not isinstance(start_res, dict) or 'data' not in start_res:
        print("Start Transfer failed:", start_res)
        return False
        
    applied_infos = start_res['data']['appliedInfos']
    upload_url = applied_infos['uploadUrl']
    media_upload_url = start_res['data']['uploadMediaUrl']
    
    print("Start Transfer Response: OK")
    print(f"Destination program folder: {upload_url}")
    print(f"Destination media folder: {media_upload_url}")
    
    def upload_file(local_path, target_dir, filename):
        print(f" - Uploading: {filename}...")
        encoded_dir = urllib.parse.quote(target_dir)
        encoded_filename = urllib.parse.quote(filename)
        upload_url_api = f"{base_url}/terminal/tools/v1/file/uploadUseBinary?targetDir={encoded_dir}&fileName={encoded_filename}"
        res = run_curl(
            upload_url_api, 
            "PUT", 
            {
                'Content-Type': 'application/octet-stream', 
                'Authorization': token
            }, 
            data_binary_file=local_path
        )
        return res
        
    # 6.1 Upload program structure files
    print("\nUploading program configuration files...")
    prog_files = ["schedule_constraint.json", "play_solution.json", "playSolutionRelation.json", "playlist0.json", "planlist.json"]
    for pf in prog_files:
        local_path = os.path.join(prog_dir, pf)
        upload_file(local_path, upload_url, pf)
        
    # 6.2 Upload thumbnail
    local_thumb_path = os.path.join(prog_dir, thumbnail_name)
    if os.path.exists(local_thumb_path):
        upload_file(local_thumb_path, upload_url, thumbnail_name)
        
    # 6.3 Upload media resources
    media_dir = os.path.join(nova_dir, "media")
    if resources and os.path.exists(media_dir):
        print("\nUploading media assets...")
        for r in resources:
            res_name = r["fileName"]
            local_res_path = os.path.join(media_dir, res_name)
            if os.path.exists(local_res_path):
                upload_file(local_res_path, media_upload_url, res_name)
            else:
                print(f"Warning: Resource file {res_name} not found in local media folder!")
                
    # 7. End Transfer
    print("\nEnding transfer and triggering play...")
    publish_time_ms = int(time.time() * 1000)
    end_payload = {
        "source": {"type": 1, "platform": 2},
        "delayTime": 0,
        "playTime": 0,
        "playImmediately": True,
        "isSupportMd5Checkout": True,
        "confirmedInfos": {
            "identifier": prog_identifier,
            "name": prog_name,
            "planListUrl": f"{upload_url}/planlist.json",
            "thumbnailUrl": f"{upload_url}/{thumbnail_name}",
            "type": "DEFAULT",
            "programBaseInfo": {
                "uuid": prog_uuid,
                "size": prog_size,
                "duration": duration,
                "programName": prog_name,
                "width": int(width),
                "height": int(height),
                "publishTime": publish_time_ms,
                "isSchedule": False
            }
        }
    }
    
    end_res = run_curl(
        f"{base_url}/terminal/core/v1/play/transfer/end", 
        "PUT", 
        {'Content-Type': 'application/json', 'Authorization': token}, 
        data_json=end_payload
    )
    print("End Transfer Response:", json.dumps(end_res, indent=2))
    
    if isinstance(end_res, dict) and end_res.get("code") == 0:
        print("\n=== PUBLISH SUCCESSFUL! The content is now playing. ===")
        return True
    else:
        print("\n=== PUBLISH FAILED ===")
        return False

if __name__ == '__main__':
    # Default to testing with a folder
    test_folder = ""
    if len(sys.argv) > 1:
        test_folder = sys.argv[1]
    
    if test_folder:
        publish_nova_folder(test_folder)
    else:
        print("Usage: python publish_local_folder.py <path_to_nova_folder>")
