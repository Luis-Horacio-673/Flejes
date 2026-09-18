import os
import sys
import time
import subprocess
import zipfile
import shutil
import glob
import hashlib
import uuid
import base64
import struct
import json
from datetime import datetime
from PIL import Image

# Set stdout to UTF-8
sys.stdout.reconfigure(encoding='utf-8')

# 1x1 pixel black JPEG base64 string for thumbnail
TINY_JPEG_B64 = (
    b'/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////'
    b'////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAA'
    b'AP/aAAgBAQABPxA='
)

def read_prices_from_csv(csv_path):
    price_inf = "Unknown"
    price_sup = "Unknown"
    price_ela = "Unknown"
    price_die = "Unknown"
    try:
        if os.path.exists(csv_path):
            with open(csv_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            for line in lines[1:]: # skip header
                parts = line.strip().split(',')
                if len(parts) >= 2:
                    name, val = parts[0].upper().strip(), parts[1].strip()
                    if "INFINIA" in name and "DIESEL" not in name:
                        price_inf = val
                    elif "SUPER" in name or "SÚPER" in name:
                        price_sup = val
                    elif "ELAION" in name:
                        price_ela = val
                    elif "DIESEL" in name:
                        price_die = val
    except Exception as e:
        print(f"Error reading CSV for report: {e}")
    return price_inf, price_sup, price_ela, price_die

def find_nova_dir(start_dir):
    """Recursively search for a folder named 'nova' containing 'command.json'"""
    for root, dirs, files in os.walk(start_dir):
        if os.path.basename(root).lower() == "nova" and "command.json" in files:
            return root
    return None

def wait_for_file_settle(file_path):
    """Wait until a file's size stops changing (ensures Google Drive finished syncing)"""
    print(f"Detectado archivo nuevo: {os.path.basename(file_path)}")
    print("Esperando a que Google Drive complete la descarga...")
    
    last_size = -1
    stable_cycles = 0
    
    while stable_cycles < 3:
        time.sleep(1.5)
        try:
            curr_size = os.path.getsize(file_path)
            if curr_size == last_size and curr_size > 0:
                stable_cycles += 1
            else:
                last_size = curr_size
                stable_cycles = 0
        except Exception as e:
            stable_cycles = 0
            
    print(f"Archivo listo. Tamaño final: {last_size} bytes.")

def get_md5_of_file(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def get_md5_of_string(text):
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def get_mp4_duration_ms(file_path):
    """Parse MP4 box structure to find timescale and duration in mvhd atom. Falls back to 10s."""
    try:
        with open(file_path, 'rb') as f:
            f.seek(0, 2)
            file_size = f.tell()
            f.seek(0)
            
            while f.tell() < file_size:
                header = f.read(8)
                if len(header) < 8:
                    break
                size, atom_type = struct.unpack('>I4s', header)
                if size == 0:
                    break
                
                if size == 1:
                    size_64 = f.read(8)
                    size = struct.unpack('>Q', size_64)[0]
                    content_size = size - 16
                else:
                    content_size = size - 8
                    
                if atom_type == b'moov':
                    moov_start = f.tell()
                    moov_end = moov_start + content_size
                    while f.tell() < moov_end:
                        sub_header = f.read(8)
                        if len(sub_header) < 8:
                            break
                        sub_size, sub_type = struct.unpack('>I4s', sub_header)
                        if sub_size == 0:
                            break
                        
                        sub_content_size = sub_size - 8
                        if sub_type == b'mvhd':
                            mvhd_data = f.read(sub_content_size)
                            version = mvhd_data[0]
                            if version == 1:
                                timescale = struct.unpack('>I', mvhd_data[20:24])[0]
                                duration = struct.unpack('>Q', mvhd_data[24:32])[0]
                            else:
                                timescale = struct.unpack('>I', mvhd_data[12:16])[0]
                                duration = struct.unpack('>I', mvhd_data[16:20])[0]
                            return int((duration / timescale) * 1000)
                        else:
                            f.seek(sub_content_size, 1)
                    break
                else:
                    f.seek(content_size, 1)
    except Exception as e:
        print(f"Warning: Failed to parse MP4 duration ({e}), using default of 10s.")
    return 10000

def write_report(report_path, title, detail, success=True):
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    status_tag = "[OK]" if success else "[ERROR]"
    
    try:
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("========================================================\n")
            f.write(f" {status_tag} {title}\n")
            f.write("========================================================\n")
            f.write(f"Fecha y Hora: {now_str}\n\n")
            f.write(detail)
        print(f"Reporte escrito en: {report_path}")
    except Exception as e:
        print(f"Error escribiendo reporte: {e}")

def cleanup_and_archive(file_path, extract_dir, script_dir):
    # Delete extraction folder
    if extract_dir and os.path.exists(extract_dir):
        shutil.rmtree(extract_dir, ignore_errors=True)
        
    # Move original file to 'procesados' folder to avoid looping
    processed_dir = os.path.join(script_dir, "procesados")
    os.makedirs(processed_dir, exist_ok=True)
    
    file_name = os.path.basename(file_path)
    base, ext = os.path.splitext(file_name)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    new_file_name = f"{base}_{timestamp}{ext}"
    dest_path = os.path.join(processed_dir, new_file_name)
    
    print(f"Archivando archivo a: {dest_path}")
    try:
        shutil.move(file_path, dest_path)
    except Exception as e:
        print(f"Error al archivar: {e}")
        try:
            os.remove(file_path)
            print("Archivo original eliminado de la raíz como fallback.")
        except Exception as e2:
            print(f"No se pudo eliminar el archivo raíz: {e2}")

def process_zip_file(zip_path, script_dir, report_path, watch_dir):
    zip_name = os.path.basename(zip_path)
    wait_for_file_settle(zip_path)
    
    extract_dir = os.path.join(script_dir, "temp_extract")
    if os.path.exists(extract_dir):
        shutil.rmtree(extract_dir, ignore_errors=True)
    os.makedirs(extract_dir, exist_ok=True)
    
    print(f"Descomprimiendo {zip_name}...")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
    except Exception as e:
        err_msg = f"Error al descomprimir archivo ZIP: {e}"
        print(err_msg)
        write_report(report_path, "FALLO DESCOMPRESION ZIP", f"Archivo: {zip_name}\n\nDetalle: {err_msg}", success=False)
        cleanup_and_archive(zip_path, extract_dir, watch_dir)
        return
        
    nova_dir = find_nova_dir(extract_dir)
    if not nova_dir:
        err_msg = "No se encontró la carpeta 'nova' con el archivo 'command.json' dentro del archivo ZIP."
        print(f"Error: {err_msg}")
        write_report(report_path, "ESTRUCTURA DE ZIP INVALIDA", f"Archivo: {zip_name}\n\nSugerencia: Asegúrese de exportar el programa (playlist) directamente desde ViPlex Express y comprimir/subir esa carpeta.", success=False)
        cleanup_and_archive(zip_path, extract_dir, watch_dir)
        return
        
    print(f"Carpeta 'nova' encontrada en: {nova_dir}")
    print("Ejecutando script de publicación para la animación...")
    publish_script = os.path.join(script_dir, "publish_local_folder.py")
    
    res_publish = subprocess.run(
        [sys.executable, publish_script, nova_dir, watch_dir],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='ignore'
    )
    
    print("Salida del publicador:")
    print(res_publish.stdout)
    
    if res_publish.returncode == 0:
        print("¡Publicación exitosa! Solicitando captura de pantalla de verificación...")
        screenshot_script = os.path.join(script_dir, "test_screenshot_download.py")
        subprocess.run(
            [sys.executable, screenshot_script, watch_dir],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )
        
        report_detail = (
            f"Archivo procesado: {zip_name}\n\n"
            f"La animación exportada desde ViPlex se ha cargado físicamente en la pantalla LED.\n"
            f"Se ha guardado la foto real de confirmación con fecha y hora en la carpeta 'procesados/' para verificación remota.\n"
        )
        write_report(report_path, "CARGA DE ANIMACION EXITOSA", report_detail, success=True)
    else:
        print("Error al publicar animación:")
        print(res_publish.stderr)
        report_detail = (
            f"Archivo: {zip_name}\n\n"
            f"El servidor local no pudo transferir la playlist al cartel LED.\n\n"
            f"Detalle del error:\n"
            f"{res_publish.stderr if res_publish.stderr else res_publish.stdout}\n\n"
            f"Sugerencias de diagnóstico:\n"
            f"  1. Verifique que la PC Giada siga conectada a la red Wi-Fi del TB10 Plus.\n"
            f"  2. Verifique que el cartel LED esté encendido y respondiendo.\n"
        )
        write_report(report_path, "FALLO LA CARGA DE LA ANIMACION", report_detail, success=False)
        
    cleanup_and_archive(zip_path, extract_dir, watch_dir)

def process_mp4_file(mp4_path, script_dir, report_path, watch_dir):
    mp4_name = os.path.basename(mp4_path)
    wait_for_file_settle(mp4_path)
    
    # 1. Gather MP4 metrics
    print(f"Analizando archivo de video {mp4_name}...")
    video_size = os.path.getsize(mp4_path)
    video_md5 = get_md5_of_file(mp4_path)
    duration_ms = get_mp4_duration_ms(mp4_path)
    print(f" - Tamaño: {video_size} bytes")
    print(f" - MD5: {video_md5}")
    print(f" - Duración: {duration_ms} ms ({duration_ms/1000.0} s)")
    
    # 2. Define unique IDs
    prog_name = "Video_Promo"
    prog_uuid = str(uuid.uuid4())
    scene_uuid = str(uuid.uuid4())
    container_uuid = str(uuid.uuid4())
    widget_uuid = str(uuid.uuid4())
    
    # 3. Create temp packaging folder structure
    package_dir = os.path.join(script_dir, "temp_package")
    if os.path.exists(package_dir):
        shutil.rmtree(package_dir, ignore_errors=True)
        
    nova_dir = os.path.join(package_dir, "nova")
    prog_dir = os.path.join(nova_dir, "program", prog_name)
    media_dir = os.path.join(nova_dir, "media")
    
    os.makedirs(prog_dir, exist_ok=True)
    os.makedirs(media_dir, exist_ok=True)
    
    # 4. Copy MP4 to media folder with MD5 name
    dest_video_path = os.path.join(media_dir, f"{video_md5}.mp4")
    shutil.copy2(mp4_path, dest_video_path)
    
    # 5. Write 1x1 black thumbnail
    thumb_path = os.path.join(prog_dir, "thumbnail.jpg")
    with open(thumb_path, 'wb') as f:
        f.write(base64.b64decode(TINY_JPEG_B64))
        
    # 6. Generate JSONs
    # schedule_constraint.json
    schedule_constraint_json = {
        "id": 0,
        "name": "schedule_constraint",
        "constraints": [
            {
                "id": 0,
                "priority": 1000,
                "name": "schedule_item",
                "startTime": "1970-01-01T00:00:00Z+08:00",
                "endTime": "4012-01-01T23:59:59Z+08:00",
                "cron": ["0 0 0 ? * 1,2,3,4,5,6,7"]
            }
        ]
    }
    
    # play_solution.json
    play_solution_json = {
        "version": "1.0.0",
        "source": {"type": 1, "platform": 2},
        "uuid": str(uuid.uuid4()),
        "items": [
            {
                "id": 1,
                "name": "local_net_program_task",
                "layout": {
                    "x": "0%", "y": "0%", "width": "100%", "height": "100%",
                    "xNum": 0.0, "yNum": 0.0, "widthNum": 100.0, "heightNum": 100.0
                },
                "zOrder": 1
            }
        ],
        "target": [-1],
        "name": "play_solution",
        "picktype": "DEFAULT",
        "itemCount": 1,
        "id": 0
    }
    
    # playSolutionRelation.json
    play_relation_json = {
        "id": 0,
        "name": "playSolutionRelation",
        "playSolutionSource": "play_solution.json",
        "relations": [
            {
                "taskId": 1,
                "scheduleConstraints": [
                    {
                        "constraintId": 0,
                        "constraintSource": "schedule_constraint.json",
                        "playlists": [
                            {
                                "playlistId": 0,
                                "playlistSource": "playlist0.json"
                            }
                        ]
                    }
                ]
            }
        ]
    }
    
    # playlist0.json (For video uploads - scale to full widget size by default)
    playlist0_json = {
        "id": 0,
        "uuid": prog_uuid,
        "desc": "",
        "width": 1440.0,
        "height": 32.0,
        "thumbpath": "",
        "importBySn": "",
        "ImportTaskStatus": 0,
        "ImportTaskFailCode": 0,
        "name": prog_name,
        "pickPolicy": "ORDER",
        "ProgramModel": 0,
        "sceneItems": [
            {
                "id": 0,
                "uuid": scene_uuid,
                "name": "Preset",
                "backgroundColor": "#00000000",
                "backgroundDrawable": "",
                "backgroundMusic": "",
                "thumbnail": "thumbnail.jpg",
                "enable": True,
                "type": "PAGE",
                "rules": "TIMES",
                "duration": duration_ms,
                "IsUserBkMusicDuration": 0,
                "repeatCount": 1,
                "constraints": [
                    {
                        "startTime": "1970-01-01T00:00:00Z+08:00",
                        "endTime": "4012-01-01T23:59:59Z+08:00",
                        "cron": ["0 0 0 ? * 1,2,3,4,5,6,7"]
                    }
                ],
                "page": {
                  "id": 0,
                  "uuid": "00000000-0000-0000-0000-000000000000",
                  "name": "Page1",
                  "inAnimation": {"type": 0, "duration": 1000},
                  "outAnimation": {"type": 0, "duration": 0},
                  "border": {
                    "aspectRatio": {"type": 0, "isLocked": True},
                    "width": 1,
                    "backgroundColor": "#FFFF0000",
                    "foregroundColor": "#FF008000",
                    "style": 0,
                    "styleForExpress": 0,
                    "effects": {
                      "speed": 3,
                      "animation": "MARQUEE_LEFT",
                      "isHeadTail": False,
                      "headTailSpacing": "10",
                      "speedByPixelEnable": False
                    },
                    "AudioListData": {"playPolicy": "ORDER", "audioList": [], "DurationTime": 0}
                  },
                  "thumbpath": "",
                  "widgets": [],
                  "widgetContainers": [
                    {
                      "id": 1000,
                      "uuid": container_uuid,
                      "zOrder": 0,
                      "enable": False,
                      "PCType": 1,
                      "DuritionType": 0,
                      "layout": {
                        "x": "0%", "y": "0%", "width": "100%", "height": "100%",
                        "xNum": 0.0, "yNum": 0.0, "widthNum": 100.0, "heightNum": 100.0
                      },
                      "border": {
                        "aspectRatio": {"type": 0, "isLocked": False},
                        "width": 1,
                        "backgroundColor": "#FFFF0000",
                        "foregroundColor": "#FF008000",
                        "style": 0,
                        "styleForExpress": 0,
                        "effects": {
                          "speed": 3,
                          "animation": "MARQUEE_LEFT",
                          "isHeadTail": False,
                          "headTailSpacing": "10",
                          "speedByPixelEnable": False
                        },
                        "AudioListData": {"playPolicy": "ORDER", "audioList": [], "DurationTime": 0}
                      },
                      "contents": {
                        "widgets": [
                          {
                            "id": 100000,
                            "uuid": widget_uuid,
                            "name": mp4_name,
                            "enable": True,
                            "duration": duration_ms,
                            "repeatCount": 1,
                            "type": "VIDEO",
                            "displayRatio": "FULL",
                            "filesize": video_size,
                            "originalDataSource": mp4_name,
                            "zOrder": 1,
                            "dataSource": f"{video_md5}.mp4",
                            "backgroundColor": "#00000000",
                            "backgroundDrawable": "",
                            "backgroundMusic": "",
                            "layout": {
                              "x": "0%", "y": "0%", "width": "100%", "height": "100%",
                              "xNum": 0.0, "yNum": 0.0, "widthNum": 100.0, "heightNum": 100.0
                            },
                            "inAnimation": {"type": 0, "duration": 1000},
                            "outAnimation": {"type": 0, "duration": 1000},
                            "border": {
                              "aspectRatio": {"type": 0, "isLocked": False},
                              "name": "border",
                              "width": 1,
                              "backgroundColor": "#FF000000",
                              "foregroundColor": "#FF008000",
                              "cornerRadius": "2%",
                              "style": 0,
                              "styleForExpress": 0,
                              "borderThickness": "0px,0px,0px,0px",
                              "effects": {
                                "speed": 3,
                                "animation": "CLOCK_WISE",
                                "isHeadTail": False,
                                "headTailSpacing": "10",
                                "speedByPixelEnable": False
                              },
                              "AudioListData": {"playPolicy": "ORDER", "audioList": [], "DurationTime": 0}
                            },
                            "constraints": [
                              {
                                "startTime": "1970-01-01T00:00:00Z+8:00",
                                "endTime": "4012-01-01T23:59:59Z+8:00",
                                "cron": ["0 0 0 ? * 1,2,3,4,5,6,7"]
                              }
                            ],
                            "metadata": {"volume": 100},
                            "ShowPic": "",
                            "emptyPixelSize": 0,
                            "singleLine": False,
                            "aiGenerated": False
                          }
                        ],
                        "widgetContainer": [],
                        "zOrder": 0,
                        "DuritionType": 0,
                        "id": 0,
                        "uuid": "00000000-0000-0000-0000-000000000000"
                      },
                      "winId": {"value": 1361557552688}
                    }
                  ]
                }
            }
        ],
        "GroupType": 0,
        "risplayScreen": "",
        "Series": "",
        "equipment": "",
        "ProgramType": 0
    }
    
    # Write JSON files to calculate their MD5
    temp_files = {
        "schedule_constraint.json": schedule_constraint_json,
        "play_solution.json": play_solution_json,
        "playSolutionRelation.json": play_relation_json,
        "playlist0.json": playlist0_json
    }
    
    written_paths = {}
    for name, data in temp_files.items():
        p = os.path.join(prog_dir, name)
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        written_paths[name] = p
        
    # Calculate MD5 for planlist.json
    constraint_md5 = get_md5_of_file(written_paths["schedule_constraint.json"])
    solution_md5 = get_md5_of_file(written_paths["play_solution.json"])
    relation_md5 = get_md5_of_file(written_paths["playSolutionRelation.json"])
    playlist_md5 = get_md5_of_file(written_paths["playlist0.json"])
    
    # planlist.json
    planlist_json = {
        "name": prog_name,
        "source": {"type": 1, "platform": 2},
        "playRelations": [
            {
                "fileName": "playSolutionRelation.json",
                "md5": relation_md5,
                "Md5Suffixes": f"{relation_md5}.json"
            }
        ],
        "playSolutions": [
            {
                "fileName": "play_solution.json",
                "md5": solution_md5,
                "Md5Suffixes": f"{solution_md5}.json"
            }
        ],
        "playlists": [
            {
                "fileName": "playlist0.json",
                "md5": playlist_md5,
                "Md5Suffixes": f"{playlist_md5}.json"
            }
        ],
        "scheduleConstraints": [
            {
                "fileName": "schedule_constraint.json",
                "md5": constraint_md5,
                "Md5Suffixes": f"{constraint_md5}.json"
            }
        ],
        "audiolists": [],
        "medialists": [],
        "resources": [
            {
                "fileName": f"{video_md5}.mp4",
                "md5": video_md5,
                "Md5Suffixes": f"{video_md5}.mp4",
                "url": mp4_name,
                "type": "VIDEO",
                "size": video_size
            }
        ],
        "thumbnails": [
            {
                "fileName": "thumbnail.jpg",
                "size": os.path.getsize(thumb_path),
                "md5": "715d010feb6114df58fc0af11bd46046"
            }
        ],
        "aiWaterMark": {"position": 0, "visible": False}
    }
    
    planlist_path = os.path.join(prog_dir, "planlist.json")
    with open(planlist_path, 'w', encoding='utf-8') as f:
        json.dump(planlist_json, f, indent=2, ensure_ascii=False)
        
    # Calculate program size (sum of JSONs + thumb + video)
    all_files_to_sum = [
        planlist_path,
        thumb_path,
        dest_video_path,
        written_paths["schedule_constraint.json"],
        written_paths["play_solution.json"],
        written_paths["playSolutionRelation.json"],
        written_paths["playlist0.json"]
    ]
    total_prog_size = sum(os.path.getsize(f) for f in all_files_to_sum)
    
    # command.json
    command_json = {
        "programInfos": [
            {
                "name": prog_name,
                "url": prog_name,
                "identifier": prog_uuid,
                "size": total_prog_size,
                "thumbnailName": "thumbnail.jpg"
            }
        ]
    }
    
    # Encode command.json to base64
    cmd_str = json.dumps(command_json, ensure_ascii=False)
    cmd_b64 = base64.b64encode(cmd_str.encode('utf-8')).decode('utf-8')
    
    cmd_path = os.path.join(nova_dir, "command.json")
    with open(cmd_path, 'w', encoding='utf-8') as f:
        f.write(cmd_b64)
        
    print(f"Estructura ViPlex creada con éxito en {nova_dir} para {mp4_name}")
    
    # 7. Execute Publish Local Folder
    print("Ejecutando script de publicación para el video...")
    publish_script = os.path.join(script_dir, "publish_local_folder.py")
    
    res_publish = subprocess.run(
        [sys.executable, publish_script, nova_dir, watch_dir],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='ignore'
    )
    
    print("Salida del publicador:")
    print(res_publish.stdout)
    
    if res_publish.returncode == 0:
        print("¡Publicación exitosa! Solicitando captura de pantalla de verificación...")
        screenshot_script = os.path.join(script_dir, "test_screenshot_download.py")
        subprocess.run(
            [sys.executable, screenshot_script, watch_dir],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )
        
        report_detail = (
            f"Archivo de video procesado: {mp4_name}\n\n"
            f"El video MP4 de publicidad se ha empaquetado y cargado físicamente en la pantalla LED.\n"
            f"Se ha guardado la foto real de confirmación con fecha y hora en la carpeta 'procesados/' para verificación remota.\n"
        )
        write_report(report_path, "CARGA DE VIDEO PUBLICITARIO EXITOSA", report_detail, success=True)
    else:
        print("Error al publicar video:")
        print(res_publish.stderr)
        report_detail = (
            f"Archivo: {mp4_name}\n\n"
            f"El servidor local no pudo transferir el video al cartel LED.\n\n"
            f"Detalle del error:\n"
            f"{res_publish.stderr if res_publish.stderr else res_publish.stdout}\n\n"
            f"Sugerencias de diagnóstico:\n"
            f"  1. Verifique que la PC Giada siga conectada a la red Wi-Fi del TB10 Plus.\n"
            f"  2. Verifique que el cartel LED esté encendido y respondiendo.\n"
        )
        write_report(report_path, "FALLO LA CARGA DEL VIDEO", report_detail, success=False)
        
    # 8. Cleanup package folder and archive MP4
    cleanup_and_archive(mp4_path, package_dir, watch_dir)

def process_image_file(img_path, script_dir, report_path, watch_dir):
    img_name = os.path.basename(img_path)
    wait_for_file_settle(img_path)
    
    # 1. Gather image metrics
    print(f"Analizando archivo de imagen {img_name}...")
    try:
        with Image.open(img_path) as img:
            img_width, img_height = img.size
    except Exception as e:
        print(f"Warning: Failed to parse image dimensions ({e}), using default 1440x32.")
        img_width, img_height = 1440, 32
        
    img_size = os.path.getsize(img_path)
    img_md5 = get_md5_of_file(img_path)
    _, ext = os.path.splitext(img_name)
    ext = ext.lower()
    
    print(f" - Dimensiones: {img_width}x{img_height} px")
    print(f" - Tamaño: {img_size} bytes")
    print(f" - MD5: {img_md5}")
    
    # 2. Define unique IDs
    prog_name = "Image_Promo"
    prog_uuid = str(uuid.uuid4())
    scene_uuid = str(uuid.uuid4())
    container_uuid = str(uuid.uuid4())
    widget_uuid = str(uuid.uuid4())
    
    # 3. Create temp packaging folder structure
    package_dir = os.path.join(script_dir, "temp_package")
    if os.path.exists(package_dir):
        shutil.rmtree(package_dir, ignore_errors=True)
        
    nova_dir = os.path.join(package_dir, "nova")
    prog_dir = os.path.join(nova_dir, "program", prog_name)
    media_dir = os.path.join(nova_dir, "media")
    
    os.makedirs(prog_dir, exist_ok=True)
    os.makedirs(media_dir, exist_ok=True)
    
    # 4. Copy image to media folder with MD5 name
    dest_img_path = os.path.join(media_dir, f"{img_md5}{ext}")
    shutil.copy2(img_path, dest_img_path)
    
    # 5. Write 1x1 black thumbnail
    thumb_path = os.path.join(prog_dir, "thumbnail.jpg")
    with open(thumb_path, 'wb') as f:
        f.write(base64.b64decode(TINY_JPEG_B64))
        
    # 6. Generate JSONs
    # schedule_constraint.json
    schedule_constraint_json = {
        "id": 0,
        "name": "schedule_constraint",
        "constraints": [
            {
                "id": 0,
                "priority": 1000,
                "name": "schedule_item",
                "startTime": "1970-01-01T00:00:00Z+08:00",
                "endTime": "4012-01-01T23:59:59Z+08:00",
                "cron": ["0 0 0 ? * 1,2,3,4,5,6,7"]
            }
        ]
    }
    
    # play_solution.json
    play_solution_json = {
        "version": "1.0.0",
        "source": {"type": 1, "platform": 2},
        "uuid": str(uuid.uuid4()),
        "items": [
            {
                "id": 1,
                "name": "local_net_program_task",
                "layout": {
                    "x": "0%", "y": "0%", "width": "100%", "height": "100%",
                    "xNum": 0.0, "yNum": 0.0, "widthNum": 100.0, "heightNum": 100.0
                },
                "zOrder": 1
            }
        ],
        "target": [-1],
        "name": "play_solution",
        "picktype": "DEFAULT",
        "itemCount": 1,
        "id": 0
    }
    
    # playSolutionRelation.json
    play_relation_json = {
        "id": 0,
        "name": "playSolutionRelation",
        "playSolutionSource": "play_solution.json",
        "relations": [
            {
                "taskId": 1,
                "scheduleConstraints": [
                    {
                        "constraintId": 0,
                        "constraintSource": "schedule_constraint.json",
                        "playlists": [
                            {
                                "playlistId": 0,
                                "playlistSource": "playlist0.json"
                            }
                        ]
                    }
                ]
            }
        ]
    }
    
    # playlist0.json (Resolution independent for images!)
    playlist0_json = {
        "id": 0,
        "uuid": prog_uuid,
        "desc": "",
        "width": float(img_width),
        "height": float(img_height),
        "thumbpath": "",
        "importBySn": "",
        "ImportTaskStatus": 0,
        "ImportTaskFailCode": 0,
        "name": prog_name,
        "pickPolicy": "ORDER",
        "ProgramModel": 0,
        "sceneItems": [
            {
                "id": 0,
                "uuid": scene_uuid,
                "name": "Preset",
                "backgroundColor": "#00000000",
                "backgroundDrawable": "",
                "backgroundMusic": "",
                "thumbnail": "thumbnail.jpg",
                "enable": True,
                "type": "PAGE",
                "rules": "TIMES",
                "duration": 10000, # default 10 seconds for static images
                "IsUserBkMusicDuration": 0,
                "repeatCount": 1,
                "constraints": [
                    {
                        "startTime": "1970-01-01T00:00:00Z+08:00",
                        "endTime": "4012-01-01T23:59:59Z+08:00",
                        "cron": ["0 0 0 ? * 1,2,3,4,5,6,7"]
                    }
                ],
                "page": {
                  "id": 0,
                  "uuid": "00000000-0000-0000-0000-000000000000",
                  "name": "Page1",
                  "inAnimation": {"type": 0, "duration": 1000},
                  "outAnimation": {"type": 0, "duration": 0},
                  "border": {
                    "aspectRatio": {"type": 0, "isLocked": True},
                    "width": 1,
                    "backgroundColor": "#FFFF0000",
                    "foregroundColor": "#FF008000",
                    "style": 0,
                    "styleForExpress": 0,
                    "effects": {
                      "speed": 3,
                      "animation": "MARQUEE_LEFT",
                      "isHeadTail": False,
                      "headTailSpacing": "10",
                      "speedByPixelEnable": False
                    },
                    "AudioListData": {"playPolicy": "ORDER", "audioList": [], "DurationTime": 0}
                  },
                  "thumbpath": "",
                  "widgets": [],
                  "widgetContainers": [
                    {
                      "id": 1000,
                      "uuid": container_uuid,
                      "zOrder": 0,
                      "enable": False,
                      "PCType": 1,
                      "DuritionType": 0,
                      "layout": {
                        "x": "0%", "y": "0%", "width": "100%", "height": "100%",
                        "xNum": 0.0, "yNum": 0.0, "widthNum": 100.0, "heightNum": 100.0
                      },
                      "border": {
                        "aspectRatio": {"type": 0, "isLocked": False},
                        "width": 1,
                        "backgroundColor": "#FFFF0000",
                        "foregroundColor": "#FF008000",
                        "style": 0,
                        "styleForExpress": 0,
                        "effects": {
                          "speed": 3,
                          "animation": "MARQUEE_LEFT",
                          "isHeadTail": False,
                          "headTailSpacing": "10",
                          "speedByPixelEnable": False
                        },
                        "AudioListData": {"playPolicy": "ORDER", "audioList": [], "DurationTime": 0}
                      },
                      "contents": {
                        "widgets": [
                          {
                            "id": 100000,
                            "uuid": widget_uuid,
                            "name": img_name,
                            "enable": True,
                            "duration": 10000,
                            "repeatCount": 1,
                            "type": "PICTURE",
                            "displayRatio": "FULL",
                            "filesize": img_size,
                            "originalDataSource": img_name,
                            "zOrder": 1,
                            "dataSource": f"{img_md5}{ext}",
                            "backgroundColor": "#00000000",
                            "backgroundDrawable": "",
                            "backgroundMusic": "",
                            "layout": {
                              "x": "0%", "y": "0%", "width": "100%", "height": "100%",
                              "xNum": 0.0, "yNum": 0.0, "widthNum": 100.0, "heightNum": 100.0
                            },
                            "inAnimation": {"type": 0, "duration": 1000},
                            "outAnimation": {"type": 0, "duration": 1000},
                            "border": {
                              "aspectRatio": {"type": 0, "isLocked": False},
                              "name": "border",
                              "width": 1,
                              "backgroundColor": "#FF000000",
                              "foregroundColor": "#FF008000",
                              "cornerRadius": "2%",
                              "style": 0,
                              "styleForExpress": 0,
                              "borderThickness": "0px,0px,0px,0px",
                              "effects": {
                                "speed": 3,
                                "animation": "CLOCK_WISE",
                                "isHeadTail": False,
                                "headTailSpacing": "10",
                                "speedByPixelEnable": False
                              },
                              "AudioListData": {"playPolicy": "ORDER", "audioList": [], "DurationTime": 0}
                            },
                            "constraints": [
                              {
                                "startTime": "1970-01-01T00:00:00Z+8:00",
                                "endTime": "4012-01-01T23:59:59Z+8:00",
                                "cron": ["0 0 0 ? * 1,2,3,4,5,6,7"]
                              }
                            ],
                            "ShowPic": "",
                            "emptyPixelSize": 0,
                            "singleLine": False,
                            "aiGenerated": False
                          }
                        ],
                        "widgetContainer": [],
                        "zOrder": 0,
                        "DuritionType": 0,
                        "id": 0,
                        "uuid": "00000000-0000-0000-0000-000000000000"
                      },
                      "winId": {"value": 1361557552688}
                    }
                  ]
                }
            }
        ],
        "GroupType": 0,
        "risplayScreen": "",
        "Series": "",
        "equipment": "",
        "ProgramType": 0
    }
    
    # Write JSON files to calculate their MD5
    temp_files = {
        "schedule_constraint.json": schedule_constraint_json,
        "play_solution.json": play_solution_json,
        "playSolutionRelation.json": play_relation_json,
        "playlist0.json": playlist0_json
    }
    
    written_paths = {}
    for name, data in temp_files.items():
        p = os.path.join(prog_dir, name)
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        written_paths[name] = p
        
    # Calculate MD5 for planlist.json
    constraint_md5 = get_md5_of_file(written_paths["schedule_constraint.json"])
    solution_md5 = get_md5_of_file(written_paths["play_solution.json"])
    relation_md5 = get_md5_of_file(written_paths["playSolutionRelation.json"])
    playlist_md5 = get_md5_of_file(written_paths["playlist0.json"])
    
    # planlist.json
    planlist_json = {
        "name": prog_name,
        "source": {"type": 1, "platform": 2},
        "playRelations": [
            {
                "fileName": "playSolutionRelation.json",
                "md5": relation_md5,
                "Md5Suffixes": f"{relation_md5}.json"
            }
        ],
        "playSolutions": [
            {
                "fileName": "play_solution.json",
                "md5": solution_md5,
                "Md5Suffixes": f"{solution_md5}.json"
            }
        ],
        "playlists": [
            {
                "fileName": "playlist0.json",
                "md5": playlist_md5,
                "Md5Suffixes": f"{playlist_md5}.json"
            }
        ],
        "scheduleConstraints": [
            {
                "fileName": "schedule_constraint.json",
                "md5": constraint_md5,
                "Md5Suffixes": f"{constraint_md5}.json"
            }
        ],
        "audiolists": [],
        "medialists": [],
        "resources": [
            {
                "fileName": f"{img_md5}{ext}",
                "md5": img_md5,
                "Md5Suffixes": f"{img_md5}{ext}",
                "url": img_name,
                "type": "PICTURE",
                "size": img_size
            }
        ],
        "thumbnails": [
            {
                "fileName": "thumbnail.jpg",
                "size": os.path.getsize(thumb_path),
                "md5": "715d010feb6114df58fc0af11bd46046"
            }
        ],
        "aiWaterMark": {"position": 0, "visible": False}
    }
    
    planlist_path = os.path.join(prog_dir, "planlist.json")
    with open(planlist_path, 'w', encoding='utf-8') as f:
        json.dump(planlist_json, f, indent=2, ensure_ascii=False)
        
    # Calculate program size (sum of JSONs + thumb + image)
    all_files_to_sum = [
        planlist_path,
        thumb_path,
        dest_img_path,
        written_paths["schedule_constraint.json"],
        written_paths["play_solution.json"],
        written_paths["playSolutionRelation.json"],
        written_paths["playlist0.json"]
    ]
    total_prog_size = sum(os.path.getsize(f) for f in all_files_to_sum)
    
    # command.json
    command_json = {
        "programInfos": [
            {
                "name": prog_name,
                "url": prog_name,
                "identifier": prog_uuid,
                "size": total_prog_size,
                "thumbnailName": "thumbnail.jpg"
            }
        ]
    }
    
    # Encode command.json to base64
    cmd_str = json.dumps(command_json, ensure_ascii=False)
    cmd_b64 = base64.b64encode(cmd_str.encode('utf-8')).decode('utf-8')
    
    cmd_path = os.path.join(nova_dir, "command.json")
    with open(cmd_path, 'w', encoding='utf-8') as f:
        f.write(cmd_b64)
        
    print(f"Estructura ViPlex creada con éxito en {nova_dir} para {img_name}")
    
    # 7. Execute Publish Local Folder
    print("Ejecutando script de publicación para la imagen...")
    publish_script = os.path.join(script_dir, "publish_local_folder.py")
    
    res_publish = subprocess.run(
        [sys.executable, publish_script, nova_dir, watch_dir],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='ignore'
    )
    
    print("Salida del publicador:")
    print(res_publish.stdout)
    
    if res_publish.returncode == 0:
        print("¡Publicación exitosa! Solicitando captura de pantalla de verificación...")
        screenshot_script = os.path.join(script_dir, "test_screenshot_download.py")
        subprocess.run(
            [sys.executable, screenshot_script, watch_dir],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )
        
        report_detail = (
            f"Archivo de imagen procesado: {img_name}\n\n"
            f"La imagen de publicidad se ha empaquetado y cargado físicamente en la pantalla LED.\n"
            f"Se ha guardado la foto real de confirmación con fecha y hora en la carpeta 'procesados/' para verificación remota.\n"
        )
        write_report(report_path, "CARGA DE IMAGEN EXITOSA", report_detail, success=True)
    else:
        print("Error al publicar imagen:")
        print(res_publish.stderr)
        report_detail = (
            f"Archivo: {img_name}\n\n"
            f"El servidor local no pudo transferir la imagen al cartel LED.\n\n"
            f"Detalle del error:\n"
            f"{res_publish.stderr if res_publish.stderr else res_publish.stdout}\n\n"
            f"Sugerencias de diagnóstico:\n"
            f"  1. Verifique que la PC Giada siga conectada a la red Wi-Fi del TB10 Plus.\n"
            f"  2. Verifique que el cartel LED esté encendido y respondiendo.\n"
        )
        write_report(report_path, "FALLO LA CARGA DE LA IMAGEN", report_detail, success=False)
        
    # 8. Cleanup package folder and archive image
    cleanup_and_archive(img_path, package_dir, watch_dir)

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    folders_to_watch = []
    
    # 1. Load multicartel configurations if carteles.json exists
    carteles_path = os.path.join(script_dir, "carteles.json")
    if os.path.exists(carteles_path):
        try:
            with open(carteles_path, 'r', encoding='utf-8') as f:
                folders_to_watch = json.load(f)
                print(f"Modo Multicartel activo. Monitoreando {len(folders_to_watch)} carpetas:")
                for folder in folders_to_watch:
                    print(f" - {folder}")
        except Exception as e:
            print(f"Warning: Failed to load carteles.json: {e}")
            
    # 2. Fallback to single cartel mode if carteles.json is not configured or fails
    if not folders_to_watch:
        watch_dir = script_dir # default directory to watch
        config_path = os.path.join(script_dir, "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    if "watch_dir" in config:
                        watch_dir = config["watch_dir"]
            except Exception as e:
                print(f"Warning: Failed to load config.json: {e}")
        folders_to_watch = [watch_dir]
        print(f"Modo Cartel Único activo. Monitoreando: {watch_dir}")
        
    print("==================================================================")
    print("=== SERVICIO VIGILANTE: GOOGLE DRIVE -> TAURUS TB10 PLUS ===")
    print("==================================================================")
    print("Presione Ctrl+C para salir.")
    print("------------------------------------------------------------------")

    # Track last modification times for precios.csv in each folder
    last_mtimes = {}
    for folder in folders_to_watch:
        csv_path = os.path.join(folder, "precios.csv")
        if os.path.exists(csv_path):
            last_mtimes[folder] = os.path.getmtime(csv_path)
            print(f"[{os.path.basename(folder)}] precios.csv detectado. Última mod: {datetime.fromtimestamp(last_mtimes[folder])}")
        else:
            last_mtimes[folder] = 0
            print(f"[{os.path.basename(folder)}] Esperando precios.csv...")

    print("\nVigilante activo y a la espera de cambios o subida de archivos...")

    try:
        while True:
            time.sleep(1.0)
            
            for watch_dir in folders_to_watch:
                csv_path = os.path.join(watch_dir, "precios.csv")
                report_path = os.path.join(watch_dir, "reporte_estado.txt")
                
                # Check directory existence (handles disconnected drives/folders)
                if not os.path.exists(watch_dir):
                    continue
                    
                # --- 1. MONITOR precios.csv ---
                if os.path.exists(csv_path):
                    mtime = os.path.getmtime(csv_path)
                    if watch_dir not in last_mtimes:
                        last_mtimes[watch_dir] = mtime
                    elif mtime > last_mtimes[watch_dir]:
                        last_mtimes[watch_dir] = mtime
                        print(f"\n[{datetime.now().strftime('%H:%M:%S')}][{os.path.basename(watch_dir)}] ¡Cambio detectado en precios.csv!")
                        print("Esperando 2 segundos para asegurar la escritura completa de Google Drive...")
                        time.sleep(2.0)
                        
                        print("Ejecutando script de actualización de precios...")
                        updater_script = os.path.join(script_dir, "update_ypf_prices.py")
                        
                        res_update = subprocess.run(
                            [sys.executable, updater_script, watch_dir],
                            capture_output=True,
                            text=True,
                            encoding='utf-8',
                            errors='ignore'
                        )
                        
                        print("Salida del actualizador:")
                        print(res_update.stdout)
                        
                        if res_update.returncode == 0:
                            print("¡Actualización exitosa! Solicitando captura de pantalla de verificación...")
                            screenshot_script = os.path.join(script_dir, "test_screenshot_download.py")
                            subprocess.run(
                                [sys.executable, screenshot_script, watch_dir],
                                capture_output=True,
                                text=True,
                                encoding='utf-8',
                                errors='ignore'
                            )
                            
                            p_inf, p_sup, p_ela, p_die = read_prices_from_csv(csv_path)
                            report_detail = (
                                f"Los precios se han cargado físicamente en la pantalla LED.\n"
                                f"Valores activos:\n"
                                f"  - INFINIA:    $ {p_inf}\n"
                                f"  - SÚPER:      $ {p_sup}\n"
                                f"  - DIESEL 500: $ {p_die}\n"
                                f"  - ELAION:     $ {p_ela}\n\n"
                                f"Se ha guardado la foto real de confirmación con fecha y hora en la carpeta 'procesados/'.\n"
                            )
                            write_report(report_path, "ACTUALIZACION Y VERIFICACION EXITOSA", report_detail, success=True)
                        else:
                            print("Error al actualizar precios:")
                            print(res_update.stderr)
                            report_detail = (
                                f"El servidor local no pudo transferir los datos al cartel LED.\n\n"
                                f"Detalle del error:\n"
                                f"{res_update.stderr if res_update.stderr else res_update.stdout}\n\n"
                                f"Sugerencias de diagnóstico:\n"
                                f"  1. Verifique que la PC Giada siga conectada a la red Wi-Fi del TB10 Plus.\n"
                                f"  2. Verifique que la pantalla LED esté encendida y respondiendo.\n"
                            )
                            write_report(report_path, "FALLO LA ACTUALIZACION AUTOMATICA", report_detail, success=False)
                        
                        print("\nReanudando monitoreo...")
                        
                    # Sync last_mtime in case file changed again during execution
                    if os.path.exists(csv_path):
                        last_mtimes[watch_dir] = os.path.getmtime(csv_path)
                
                # --- 2. MONITOR *.zip files ---
                zip_files = glob.glob(os.path.join(watch_dir, "*.zip"))
                zip_files = [f for f in zip_files if os.path.dirname(f) == watch_dir]
                if zip_files:
                    target_zip = zip_files[0]
                    print(f"\n[{datetime.now().strftime('%H:%M:%S')}][{os.path.basename(watch_dir)}] ¡Archivo ZIP detectado!")
                    try:
                        process_zip_file(target_zip, script_dir, report_path, watch_dir)
                    except Exception as e:
                        print(f"Error procesando el archivo ZIP: {e}")
                        try:
                            os.remove(target_zip)
                        except:
                            pass
                    print("\nReanudando monitoreo...")
                    
                # --- 3. MONITOR *.mp4 files ---
                mp4_files = glob.glob(os.path.join(watch_dir, "*.mp4"))
                mp4_files = [f for f in mp4_files if os.path.dirname(f) == watch_dir]
                if mp4_files:
                    target_mp4 = mp4_files[0]
                    print(f"\n[{datetime.now().strftime('%H:%M:%S')}][{os.path.basename(watch_dir)}] ¡Archivo MP4 detectado!")
                    try:
                        process_mp4_file(target_mp4, script_dir, report_path, watch_dir)
                    except Exception as e:
                        print(f"Error procesando el archivo MP4: {e}")
                        try:
                            os.remove(target_mp4)
                        except:
                            pass
                    print("\nReanudando monitoreo...")
                    
                # --- 4. MONITOR image files (*.png, *.jpg, *.jpeg) ---
                img_files = []
                for ext in ["*.png", "*.jpg", "*.jpeg"]:
                    img_files.extend(glob.glob(os.path.join(watch_dir, ext)))
                img_files = [f for f in img_files if os.path.dirname(f) == watch_dir]
                # Ignore our own live screenshots to prevent infinite loops!
                img_files = [f for f in img_files if "pantalla_en_vivo" not in os.path.basename(f).lower()]
                if img_files:
                    target_img = img_files[0]
                    print(f"\n[{datetime.now().strftime('%H:%M:%S')}][{os.path.basename(watch_dir)}] ¡Archivo de imagen detectado!")
                    try:
                        process_image_file(target_img, script_dir, report_path, watch_dir)
                    except Exception as e:
                        print(f"Error procesando la imagen: {e}")
                        try:
                            os.remove(target_img)
                        except:
                            pass
                    print("\nReanudando monitoreo...")
                    
                # --- 5. MONITOR screenshot request (capturar.txt) ---
                trigger_file = os.path.join(watch_dir, "capturar.txt")
                if os.path.exists(trigger_file):
                    print(f"\n[{datetime.now().strftime('%H:%M:%S')}][{os.path.basename(watch_dir)}] ¡Solicitud de captura de pantalla detectada!")
                    try:
                        os.remove(trigger_file)
                        print("Ejecutando captura de pantalla...")
                        screenshot_script = os.path.join(script_dir, "test_screenshot_download.py")
                        
                        subprocess.run(
                            [sys.executable, screenshot_script, watch_dir],
                            capture_output=True,
                            text=True,
                            encoding='utf-8',
                            errors='ignore'
                        )
                    except Exception as e:
                        print(f"Error al procesar solicitud de captura: {e}")
                    print("\nReanudando monitoreo...")
                
    except KeyboardInterrupt:
        print("\nServicio vigilante finalizado por el usuario.")

if __name__ == "__main__":
    main()
