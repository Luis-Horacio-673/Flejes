import subprocess
import json
import urllib.parse
import os
import sys
import base64
import time
from PIL import Image, ImageDraw, ImageFont

# Set stdout to UTF-8
sys.stdout.reconfigure(encoding='utf-8')

sn = "25816A000001193"
ip = "192.168.41.1"
base_url = f"https://{ip}:16674"

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

def update_image_prices(img_path, price_infinia, price_super, price_elaion, price_diesel):
    print(f"Modifying price image at: {img_path}")
    img = Image.open(img_path).convert('RGBA')
    draw = ImageDraw.Draw(img)
    
    # 1. Clear previous text areas (retaining yellow borders at Y=0 and Y=31)
    # Infinia box: X from 181 to 408, Y from 1 to 30
    draw.rectangle([181, 1, 408, 30], fill=(0, 0, 0, 255))
    # Super box: X from 411 to 638, Y from 1 to 30
    draw.rectangle([411, 1, 638, 30], fill=(0, 0, 0, 255))
    # Diesel 500 box: X from 641 to 958, Y from 1 to 30
    draw.rectangle([641, 1, 958, 30], fill=(0, 0, 0, 255))
    # Elaion text box (after oil bottle at 962..1065): X from 1066 to 1438, Y from 1 to 30
    draw.rectangle([1066, 1, 1438, 30], fill=(0, 0, 0, 255))
    
    # Ensure dividers and borders are crisp across the entire width
    yellow_color = (255, 242, 0, 255)
    # Divider 3 (Super / Diesel 500): 639, 640
    draw.line([(639, 0), (639, 31)], fill=yellow_color)
    draw.line([(640, 0), (640, 31)], fill=yellow_color)
    # Divider 4 (Diesel 500 / Elaion): 959, 960
    draw.line([(959, 0), (959, 31)], fill=yellow_color)
    draw.line([(960, 0), (960, 31)], fill=yellow_color)
    # 1px black margin before bottle
    draw.line([(961, 1), (961, 30)], fill=(0, 0, 0, 255))
    # Right border
    draw.line([(1439, 0), (1439, 31)], fill=yellow_color)
    # Top and bottom borders
    draw.line([(0, 0), (1439, 0)], fill=yellow_color)
    draw.line([(0, 31), (1439, 31)], fill=yellow_color)
    
    # 2. Load Font (Segoe UI Bold or Arial Bold)
    font_path = r"C:\Windows\Fonts\segoeuib.ttf"
    if not os.path.exists(font_path):
        font_path = r"C:\Windows\Fonts\arialbd.ttf"
        
    font_size = 28
    font = ImageFont.truetype(font_path, font_size)
    cyan_color = (0, 162, 232, 255) # Hex #00a2e8
    
    # 3. Draw Infinia price (Center X: 294)
    infinia_text = f"INFINIA: $ {price_infinia}"
    bbox_inf = draw.textbbox((0, 0), infinia_text, font=font)
    w_inf = bbox_inf[2] - bbox_inf[0]
    h_inf = bbox_inf[3] - bbox_inf[1]
    x_inf = 294 - (w_inf // 2)
    y_target_inf = (32 - h_inf) // 2
    y_inf = y_target_inf - bbox_inf[1]
    draw.text((x_inf, y_inf), infinia_text, fill=cyan_color, font=font)
    
    # 4. Draw Super price (Center X: 525)
    super_text = f"SÚPER: $ {price_super}"
    bbox_sup = draw.textbbox((0, 0), super_text, font=font)
    w_sup = bbox_sup[2] - bbox_sup[0]
    h_sup = bbox_sup[3] - bbox_sup[1]
    x_sup = 525 - (w_sup // 2)
    y_target_sup = (32 - h_sup) // 2
    y_sup = y_target_sup - bbox_sup[1]
    draw.text((x_sup, y_sup), super_text, fill=cyan_color, font=font)
    
    # 5. Draw Diesel 500 price (Center X: 800)
    diesel_text = f"DIESEL 500 $ {price_diesel}"
    bbox_die = draw.textbbox((0, 0), diesel_text, font=font)
    w_die = bbox_die[2] - bbox_die[0]
    h_die = bbox_die[3] - bbox_die[1]
    x_die = 800 - (w_die // 2)
    y_target_die = (32 - h_die) // 2
    y_die = y_target_die - bbox_die[1]
    draw.text((x_die, y_die), diesel_text, fill=cyan_color, font=font)
    
    # 6. Draw Elaion price (Center X: 1252)
    elaion_text = f"ELAION $ {price_elaion}"
    bbox_ela = draw.textbbox((0, 0), elaion_text, font=font)
    w_ela = bbox_ela[2] - bbox_ela[0]
    h_ela = bbox_ela[3] - bbox_ela[1]
    x_ela = 1252 - (w_ela // 2)
    y_target_ela = (32 - h_ela) // 2
    y_ela = y_target_ela - bbox_ela[1]
    draw.text((x_ela, y_ela), elaion_text, fill=cyan_color, font=font)
    
    img.save(img_path)
    print("Image modified and saved successfully.")
    
    # Update player thumbnail
    thumb_path = os.path.join(os.path.dirname(os.path.dirname(img_path)), "program", "YPF_paint", "715d010feb6114df58fc0af11bd46046.jpg")
    if os.path.exists(thumb_path):
        try:
            img.convert('RGB').save(thumb_path, format="JPEG", quality=95)
            print(f"Thumbnail updated successfully at {thumb_path}.")
        except Exception as e:
            print(f"Warning: could not update thumbnail: {e}")

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # If a watch_dir is passed, use it!
    watch_dir_path = script_dir
    if len(sys.argv) > 1:
        watch_dir_path = sys.argv[1]
        
    csv_path = os.path.join(watch_dir_path, "precios.csv")
    
    # 1. Read or Create precios.csv
    if not os.path.exists(csv_path):
        print(f"Creating default CSV file at: {csv_path}")
        with open(csv_path, 'w', encoding='utf-8') as f:
            f.write("combustible,precio\n")
            f.write("INFINIA,2240\n")
            f.write("SUPER,2028\n")
            f.write("ELAION,15220\n")
            f.write("DIESEL 500,2100\n")
            
    price_inf = "2240"
    price_sup = "2028"
    price_elaion = "15220"
    price_diesel = "2100"
    
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        for line in lines[1:]: # skip header
            parts = line.strip().split(',')
            if len(parts) >= 2:
                name = parts[0].upper().strip()
                val = parts[1].strip()
                if "INFINIA" in name and "DIESEL" not in name:
                    price_inf = val
                elif "SUPER" in name or "SÚPER" in name:
                    price_sup = val
                elif "ELAION" in name:
                    price_elaion = val
                elif "DIESEL" in name:
                    price_diesel = val
    except Exception as e:
        print(f"Error reading CSV, using default prices. Error: {e}")
        
    print(f"Prices read from CSV -> Infinia: ${price_inf} | Super: ${price_sup} | Diesel 500: ${price_diesel} | Elaion: ${price_elaion}")
    
    # 2. Modify YPF image
    nova_dir = os.path.join(script_dir, "YPF_precios", "nova")
    img_name = "5c913c17056b84c8cd0093ae8f5f6360.png"
    img_path = os.path.join(nova_dir, "media", img_name)
    
    if not os.path.exists(img_path):
        print(f"Error: Target image not found at {img_path}!")
        sys.exit(1)
        
    update_image_prices(img_path, price_inf, price_sup, price_elaion, price_diesel)
    
    # 3. Read and decode command.json
    cmd_path = os.path.join(nova_dir, "command.json")
    with open(cmd_path, 'r', encoding='utf-8') as f:
        cmd_b64 = f.read().strip()
        
    cmd_json_str = base64.b64decode(cmd_b64).decode('utf-8')
    cmd_data = json.loads(cmd_json_str)
    
    prog_info = cmd_data["programInfos"][0]
    prog_name = prog_info["name"]
    prog_url = prog_info["url"]
    prog_identifier = prog_info["identifier"]
    prog_size = prog_info["size"]
    thumbnail_name = prog_info["thumbnailName"]
    
    prog_dir = os.path.join(nova_dir, "program", prog_url)
    planlist_path = os.path.join(prog_dir, "planlist.json")
    playlist_path = os.path.join(prog_dir, "playlist0.json")
    
    with open(planlist_path, 'r', encoding='utf-8') as f:
        plan_data = json.load(f)
    with open(playlist_path, 'r', encoding='utf-8') as f:
        play_data = json.load(f)
        
    prog_uuid = play_data["uuid"]
    width = play_data["width"]
    height = play_data["height"]
    
    duration = 0
    if play_data.get("sceneItems"):
        for item in play_data["sceneItems"]:
            duration += item.get("duration", 0)
    if duration == 0:
        duration = 10000
        
    # 4. Login
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
        sys.exit(1)
        
    token = login_res['data']['token']
    print(f"Login success! Token: {token}")
    
    # 5. Start Transfer
    resources = plan_data.get("resources", [])
    check_files = []
    file_size_infos = []
    total_media_size = 0
    
    # Update resource size since we modified the PNG file!
    new_img_size = os.path.getsize(img_path)
    for r in resources:
        res_name = r["fileName"]
        res_size = new_img_size if res_name == img_name else r["size"]
        check_files.append(res_name)
        file_size_infos.append({"name": res_name, "size": res_size})
        total_media_size += res_size
        
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
        sys.exit(1)
        
    applied_infos = start_res['data']['appliedInfos']
    upload_url = applied_infos['uploadUrl']
    media_upload_url = start_res['data']['uploadMediaUrl']
    
    def upload_file(local_path, target_dir, filename):
        print(f" - Uploading: {filename}...")
        encoded_dir = urllib.parse.quote(target_dir)
        encoded_filename = urllib.parse.quote(filename)
        upload_url_api = f"{base_url}/terminal/tools/v1/file/uploadUseBinary?targetDir={encoded_dir}&fileName={encoded_filename}"
        return run_curl(
            upload_url_api, 
            "PUT", 
            {
                'Content-Type': 'application/octet-stream', 
                'Authorization': token
            }, 
            data_binary_file=local_path
        )
        
    print("\nUploading program configuration files...")
    prog_files = ["schedule_constraint.json", "play_solution.json", "playSolutionRelation.json", "playlist0.json", "planlist.json"]
    for pf in prog_files:
        local_path = os.path.join(prog_dir, pf)
        upload_file(local_path, upload_url, pf)
        
    # Upload thumbnail
    local_thumb_path = os.path.join(prog_dir, thumbnail_name)
    if os.path.exists(local_thumb_path):
        upload_file(local_thumb_path, upload_url, thumbnail_name)
        
    # Upload media resources
    print("\nUploading media assets...")
    for r in resources:
        res_name = r["fileName"]
        local_res_path = os.path.join(script_dir, "YPF_precios", "nova", "media", res_name)
        if os.path.exists(local_res_path):
            upload_file(local_res_path, media_upload_url, res_name)
            
    # 7. End Transfer
    print("\nEnding transfer and playing...")
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
    
    if isinstance(end_res, dict) and end_res.get("code") == 0:
        print("\n=======================================================")
        print("=== ¡PRECIOS ACTUALIZADOS EXITOSAMENTE EN PANTALLA! ===")
        print(f"   Infinia: ${price_inf} | Súper: ${price_sup} | Diesel 500: ${price_diesel} | Elaion: ${price_elaion}")
        print("=======================================================")
    else:
        print("\n=== ERROR AL FINALIZAR LA ACTUALIZACION ===")
        print(end_res)

if __name__ == '__main__':
    main()
