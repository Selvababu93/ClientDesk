import asyncio, json, os, platform, socket, time, base64, subprocess, sys
import psutil, requests, websockets

API_URL = os.getenv("API_URL", "http://localhost:8000")
WS_URL  = os.getenv("WS_URL",  "ws://localhost:8000")
TOKEN_FILE = os.getenv("TOKEN_FILE", "./agent_token.txt")
AGENT_VERSION = "0.1.0"

def read_token():
    if os.path.exists(TOKEN_FILE):
        return open(TOKEN_FILE,"r").read().strip()
    # register
    payload = {
        "hostname": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()}",
        "arch": platform.machine(),
        "agent_version": AGENT_VERSION
    }
    r = requests.post(f"{API_URL}/register", json=payload, timeout=10)
    r.raise_for_status()
    tok = r.json()["token"]
    open(TOKEN_FILE,"w").write(tok)
    return tok

def collect_metrics():
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory().percent

    # pick first partition instead of "/"
    partitions = psutil.disk_partitions()
    root = partitions[0].mountpoint if partitions else "/"
    disk = psutil.disk_usage(root).percent

    boot = psutil.boot_time()
    uptime = time.time() - boot
    battery_pct = None
    try:
        if psutil.sensors_battery():
            battery_pct = psutil.sensors_battery().percent
    except Exception:
        pass

    details = {
        "load_avg": getattr(os, "getloadavg", lambda: (0,0,0))(),
        "disks": {p.mountpoint: psutil.disk_usage(p.mountpoint).percent for p in partitions if p.fstype},
    }
    return dict(cpu=cpu, mem=mem, disk=disk, uptime_sec=uptime, battery_pct=battery_pct, details=details)

def run_shell(cmd: str) -> tuple[int,str]:
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
                    cmd_id = data["cmd_id"]; kind = data["kind"]; payload = data.get("payload") or ""
                    status = "done"; result = ""
                    try:
                        if kind == "shell":
                            rc, out = run_shell(payload)
                            result = f"rc={rc}\n{out}"
                        elif kind == "restart":
                            result = "restarting"; do_restart()
                        elif kind == "shutdown":
                            result = "shutting down"; do_shutdown()
                        elif kind == "script":
                            # payload can be a base64 script text to run with /bin/bash or powershell
                            script = base64.b64decode(payload).decode("utf-8", errors="ignore")
                            if platform.system() == "Windows":
                                # run via powershell
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

async def metrics_loop(token: str):
    while True:
        try:
            m = collect_metrics()
            requests.post(f"{API_URL}/metrics", headers={"Authorization": f"Bearer {token}"}, json=m, timeout=10)
        except Exception:
            pass
        await asyncio.sleep(15)

def get_device_id(token: str) -> int:
    # light touch: call /heartbeat to update and read device_id from 401? Simpler:
    # After register we had device_id, but we didn’t persist. For simplicity, query /devices (admin) is off limits.
    # So we’ll just use WS path without server validating device_id mapping; server trusts path plus token session.
    # To keep consistent with server, we can store device_id when registering:
    return int(os.getenv("DEVICE_ID", "0"))

def ensure_device_id(token: str) -> int:
    # store device_id alongside token at initial register
    if os.path.exists(TOKEN_FILE) and ":" in open(TOKEN_FILE).read():
        t, did = open(TOKEN_FILE).read().split(":",1)
        if t == token: return int(did)
    # re-register to fetch new device_id if missing
    payload = {
        "hostname": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()}",
        "arch": platform.machine(),
        "agent_version": AGENT_VERSION
    }
    r = requests.post(f"{API_URL}/register", json=payload, timeout=10)
    r.raise_for_status()
    data = r.json()
    open(TOKEN_FILE,"w").write(f"{data['token']}:{data['device_id']}")
    return int(data["device_id"])

async def async_main(token, device_id):
    await asyncio.gather(
        metrics_loop(token),
        ws_loop(token, device_id)
    )

def main():
    token_raw = read_token()
    # token file may be "token" or "token:device_id"; normalize
    if ":" in token_raw:
        token, did = token_raw.split(":", 1)
        device_id = int(did)
    else:
        token = token_raw
        device_id = ensure_device_id(token)

    # initial heartbeat
    try:
        requests.post(f"{API_URL}/heartbeat", headers={"Authorization": f"Bearer {token}"}, timeout=5)
    except Exception:
        pass

    # Run the async main coroutine
    asyncio.run(async_main(token, device_id))

if __name__ == "__main__":
    if platform.system() != "Windows":
        try:
            if os.geteuid() != 0:
                print("Warning: not running as root")
        except AttributeError:
            pass

    main()
