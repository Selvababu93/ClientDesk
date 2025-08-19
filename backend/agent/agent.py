import asyncio, signal
import base64
import json
import os
import platform
import socket
import subprocess
import time
import shutil

import psutil
import requests
import websockets
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ---------------- CONFIG ----------------
API_URL = os.getenv("API_URL", "http://localhost:8000")
WS_URL = os.getenv("WS_URL", "ws://localhost:8000")
TOKEN_FILE = os.getenv("TOKEN_FILE", "./agent_token.txt")
AGENT_VERSION = "0.1.0"

WATCH_FOLDERS = ["C:/Users/Imixadmin/Pictures/Smart Shooter 4", "D:/Photos/Incoming"]
DEST_FOLDER = "C:/Users/Imixadmin/Pictures/Static"  # Optional copy destination
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp"}
# ----------------------------------------

# ---------------- TOKEN -----------------
def read_token() -> str:
    """Read the stored token, strip device_id if present."""
    if os.path.exists(TOKEN_FILE):
        tok = open(TOKEN_FILE, "r").read().strip()
        if ":" in tok:
            tok, _ = tok.split(":", 1)
        return tok
    # if file missing: register fresh
    payload = {
        "hostname": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()}",
        "arch": platform.machine(),
        "agent_version": AGENT_VERSION
    }
    r = requests.post(f"{API_URL}/register", json=payload, timeout=10)
    r.raise_for_status()
    tok = r.json()["token"]
    open(TOKEN_FILE, "w").write(tok)
    return tok


def ensure_device_id(token: str) -> int:
    if os.path.exists(TOKEN_FILE) and ":" in open(TOKEN_FILE).read():
        t, did = open(TOKEN_FILE).read().split(":", 1)
        if t == token:
            return int(did)
    payload = {
        "hostname": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()}",
        "arch": platform.machine(),
        "agent_version": AGENT_VERSION
    }
    r = requests.post(f"{API_URL}/register", json=payload, timeout=10)
    r.raise_for_status()
    data = r.json()
    open(TOKEN_FILE, "w").write(f"{data['token']}:{data['device_id']}")
    return int(data["device_id"])

# -------------- METRICS ----------------
def collect_metrics():
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory().percent
    disk = psutil.disk_usage("/").percent
    uptime = time.time() - psutil.boot_time()
    battery_pct = None
    try:
        if psutil.sensors_battery():
            battery_pct = psutil.sensors_battery().percent
    except Exception:
        pass

    details = {
        "load_avg": getattr(os, "getloadavg", lambda: (0, 0, 0))(),
        "disks": {p.mountpoint: psutil.disk_usage(p.mountpoint).percent for p in psutil.disk_partitions() if p.fstype},
    }
    return dict(cpu=cpu, mem=mem, disk=disk, uptime_sec=uptime, battery_pct=battery_pct, details=details)

async def metrics_loop(token: str):
    while True:
        try:
            m = collect_metrics()
            requests.post(f"{API_URL}/metrics", headers={"Authorization": f"Bearer {token}"}, json=m, timeout=10)
        except Exception:
            pass
        await asyncio.sleep(15)

# ------------- SHELL / RESTART / SHUTDOWN --------------
def run_shell(cmd: str):
    try:
        out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)
        return out.returncode, (out.stdout + "\n" + out.stderr).strip()
    except Exception as e:
        return 1, f"error: {e}"

def do_restart():
    if platform.system() == "Windows":
        subprocess.Popen("shutdown /r /t 0", shell=True)
    else:
        subprocess.Popen("shutdown -r now", shell=True)

def do_shutdown():
    if platform.system() == "Windows":
        subprocess.Popen("shutdown /s /t 0", shell=True)
    else:
        subprocess.Popen("shutdown -h now", shell=True)

# ---------------- WEBSOCKET ----------------
async def ws_loop(token: str, device_id: int):
    url = f"{WS_URL}/ws/agent/{device_id}"
    headers = [("Authorization", f"Bearer {token}")]
    while True:
        try:
            async with websockets.connect(url, extra_headers=headers, ping_interval=20, ping_timeout=20) as ws:
                await ws.send("hello")
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    cmd_id = data["cmd_id"]
                    kind = data["kind"]
                    payload = data.get("payload") or ""
                    status = "done"
                    result = ""
                    try:
                        if kind == "shell":
                            rc, out = run_shell(payload)
                            result = f"rc={rc}\n{out}"
                        elif kind == "restart":
                            result = "restarting"; do_restart()
                        elif kind == "shutdown":
                            result = "shutting down"; do_shutdown()
                        elif kind == "script":
                            script = base64.b64decode(payload).decode("utf-8", errors="ignore")
                            if platform.system() == "Windows":
                                rc, out = run_shell(f'powershell -NoProfile -Command "{script}"')
                            else:
                                rc, out = run_shell(f"/bin/bash -lc '{script}'")
                            result = f"rc={rc}\n{out}"
                        else:
                            status = "error"; result = f"unknown kind: {kind}"
                    except Exception as e:
                        status = "error"; result = f"exception: {e}"

                    try:
                        requests.post(f"{API_URL}/commands/{cmd_id}/status",
                                      headers={"Authorization": f"Bearer {token}"},
                                      json={"status": status, "result": result}, timeout=10)
                    except Exception:
                        pass
        except Exception:
            await asyncio.sleep(5)

# ---------------- FOLDER MONITORING ----------------
class ImageHandler(FileSystemEventHandler):
    def __init__(self, token: str):
        self.token = token

    def on_created(self, event):
        if not event.is_directory and os.path.splitext(event.src_path)[1].lower() in ALLOWED_EXTENSIONS:
            file_path = event.src_path
            file_name = os.path.basename(file_path)

            # Wait until file is fully available
            for _ in range(10):  # try 10 times
                try:
                    size = os.path.getsize(file_path)
                    with open(file_path, "rb") as f:
                        f.read(1)
                    break  # file is ready
                except (PermissionError, OSError):
                    time.sleep(0.5)
            else:
                print(f"Failed to access file {file_name}")
                return

            created = os.path.getctime(file_path)
            print(f"New image detected: {file_name}, Size: {size}, Created: {created}")

            if DEST_FOLDER:
                os.makedirs(DEST_FOLDER, exist_ok=True)

                dest_path = os.path.join(DEST_FOLDER, file_name)
                for _ in range(10):
                    try:
                        shutil.copy2(file_path, dest_path)
                        break  # success
                    except (PermissionError, OSError):
                        time.sleep(0.5)
            else:
                print(f"Failed to copy file {file_name} to destination")


            try:
                requests.post(f"{API_URL}/new_image",
                              headers={"Authorization": f"Bearer {self.token}"},
                              json={"filename": file_name, "size": size, "created": created},
                              timeout=10)
            except Exception:
                pass


def start_monitoring(token: str):
    observer = Observer()
    handler = ImageHandler(token)
    for folder in WATCH_FOLDERS:
        if os.path.exists(folder):
            observer.schedule(handler, folder, recursive=False)
        else:
            print(f"Warning: folder {folder} does not exist")
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

async def monitor_loop(token: str):
    await asyncio.to_thread(start_monitoring, token)

# ---------------- MAIN ----------------

async def async_main():
    global observer

    # initialize token/device
    token = read_token()
    device_id = ensure_device_id(token)

    # start folder monitoring
    observer = Observer()
    handler = ImageHandler(token)
    for folder in WATCH_FOLDERS:
        if os.path.exists(folder):
            observer.schedule(handler, folder, recursive=False)
        else:
            print(f"Warning: folder {folder} does not exist")
    observer.start()

    # create async tasks
    metrics_task = asyncio.create_task(metrics_loop(token))
    ws_task = asyncio.create_task(ws_loop(token, device_id))

    try:
        # wait forever, handle Ctrl+C
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("Shutting down...")

    # stop observer
    observer.stop()
    observer.join()

    # cancel async tasks
    metrics_task.cancel()
    ws_task.cancel()
    await asyncio.gather(metrics_task, ws_task, return_exceptions=True)
    print("Agent stopped cleanly.")


if __name__ == "__main__":
    asyncio.run(async_main())
