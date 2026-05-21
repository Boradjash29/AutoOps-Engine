# FILE: api/main.py
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
import psutil
import docker

def get_host_disk_usage():
    disk_path = "/host" if os.path.exists("/host") else "/"
    try:
        return psutil.disk_usage(disk_path).percent
    except Exception:
        return psutil.disk_usage("/").percent
import time
import os
import sys
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from api.database import (init_db, get_history, insert_server, get_all_servers, 
                         get_server, delete_server, get_remote_history, 
                         insert_scan_result, get_latest_scan, get_scan_history,
                         update_server_status)
from api.models import (HealthResponse, ContainerResponse, RestartResponse, 
                       TestAlertResponse, CleanupPreviewResponse, ServerCreate)
from alerts.telegram_alert import send

# Note: In a real module loading scenario, ai, agents, and security might be imported later or here
# We try to import them if available, else stub them out for initial load
try:
    from ai.anomaly_detector import AnomalyDetector
    from ai.trainer import ModelTrainer
    detector = AnomalyDetector()
    trainer = ModelTrainer(detector)
except ImportError:
    detector = None
    trainer = None

try:
    from agents.agent_manager import AgentManager
    from agents.ssh_agent import SSHAgent
    agent_manager = AgentManager()
except ImportError:
    agent_manager = None
    SSHAgent = None

try:
    from security.scanner import SecurityScanner
    scanner = SecurityScanner()
except ImportError:
    scanner = None

try:
    from prometheus_client import Gauge, Counter, generate_latest, CONTENT_TYPE_LATEST
    # Prometheus Gauges
    cpu_gauge = Gauge('autoops_cpu_percent', 'CPU usage percent')
    ram_gauge = Gauge('autoops_ram_percent', 'RAM usage percent')
    disk_gauge = Gauge('autoops_disk_percent', 'Disk usage percent')
    container_total = Gauge('autoops_containers_total', 'Total containers')
    container_up = Gauge('autoops_containers_running', 'Running containers')
    restart_counter = Counter('autoops_container_restarts_total', 'Total container auto-restarts', ['container_name'])
    anomaly_gauge = Gauge('autoops_anomaly_score', 'Latest anomaly score')
    alert_counter = Counter('autoops_alerts_total', 'Total alerts sent', ['alert_type'])
    prometheus_available = True
except ImportError:
    prometheus_available = False


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, data: dict):
        message = json.dumps(data)
        dead = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                dead.append(connection)
        for d in dead:
            if d in self.active_connections:
                self.active_connections.remove(d)

manager = ConnectionManager()
app = FastAPI(title="AutoOps Engine API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the dashboard HTML directly from the API (for single-container Render deployment)
from fastapi.responses import HTMLResponse

@app.get("/dashboard", response_class=HTMLResponse)
def serve_dashboard():
    template_path = os.path.join(os.path.dirname(__file__), '..', 'dashboard', 'templates', 'index.html')
    try:
        with open(template_path, 'r') as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Dashboard not found</h1>"

async def periodic_update():
    """Send a fleet-wide status update to Telegram every 50 seconds.
    Covers the local machine + all online registered servers.
    Not an alert — just a periodic health snapshot.
    """
    while True:
        await asyncio.sleep(50)
        try:
            ts = time.strftime('%Y-%m-%d %H:%M:%S')

            # --- Local machine ---
            cpu  = psutil.cpu_percent(interval=1)
            ram  = psutil.virtual_memory().percent
            disk = get_host_disk_usage()
            boot_time    = psutil.boot_time()
            uptime_hours = round((time.time() - boot_time) / 3600, 2)

            def _bar(val):
                filled = int(val / 10)
                return '█' * filled + '░' * (10 - filled) + f' {val:.1f}%'

            lines = [
                f"🖥 *AutoOps Engine — Fleet Update*",
                f"🕒 `{ts}`",
                "",
                "*📍 Local Machine*",
                f"  CPU  {_bar(cpu)}",
                f"  RAM  {_bar(ram)}",
                f"  Disk {_bar(disk)}",
                f"  ⏱ Uptime: {uptime_hours:.1f}h",
            ]

            # --- Docker containers (best-effort) ---
            try:
                client = docker.from_env()
                containers = client.containers.list(all=True)
                running_c  = sum(1 for c in containers if c.status == 'running')
                lines.append(f"  🐳 Containers: {running_c}/{len(containers)} running")
            except Exception:
                pass

            # --- Remote servers ---
            servers = get_all_servers()
            online_servers = [s for s in servers if s.get('status', '').lower() == 'online']

            if online_servers and SSHAgent:
                lines.append("")
                lines.append("*🌐 Remote Servers*")
                for s in online_servers:
                    try:
                        agent   = SSHAgent(s['host'], s['port'], s['username'],
                                           s['ssh_key_path'], s['password'])
                        metrics = agent.collect_metrics()
                        if metrics['reachable']:
                            update_server_status(s['id'], 'online', time.strftime('%Y-%m-%d %H:%M:%S'))
                            from api.database import insert_remote_metric
                            insert_remote_metric(s['id'], metrics['cpu'], metrics['ram'],
                                                 metrics['disk'], metrics['uptime_hours'])
                            lines += [
                                f"  *{s['name']}* (`{s['host']}`)",
                                f"    CPU  {_bar(metrics['cpu'])}",
                                f"    RAM  {_bar(metrics['ram'])}",
                                f"    Disk {_bar(metrics['disk'])}",
                                f"    ⏱ Uptime: {metrics['uptime_hours']:.1f}h",
                            ]
                        else:
                            update_server_status(s['id'], 'offline', time.strftime('%Y-%m-%d %H:%M:%S'))
                            lines.append(f"  *{s['name']}* (`{s['host']}`) — 🔴 Unreachable")
                    except Exception as e:
                        lines.append(f"  *{s['name']}* — ⚠️ Error: {e}")

            message = "\n".join(lines)
            send(message)

        except Exception as e:
            print(f"[periodic_update] Error: {e}")

@app.on_event("startup")
async def startup_event():
    init_db()
    if agent_manager:
        agent_manager.start()
    if trainer:
        trainer.start()
    asyncio.create_task(periodic_update())

@app.on_event("shutdown")
def shutdown_event():
    if agent_manager:
        agent_manager.stop()
    if trainer:
        trainer.running = False

# WebSocket Endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

async def push_metrics(data: dict):
    await manager.broadcast(data)

def update_prometheus_metrics(cpu, ram, disk, anomaly_score=0.0):
    if prometheus_available:
        cpu_gauge.set(cpu)
        ram_gauge.set(ram)
        disk_gauge.set(disk)
        anomaly_gauge.set(anomaly_score)

# Prometheus Metrics Endpoint
@app.get("/metrics")
async def metrics():
    if prometheus_available:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
    raise HTTPException(status_code=501, detail="Prometheus client not installed")

@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
def root():
    template_path = os.path.join(os.path.dirname(__file__), '..', 'dashboard', 'templates', 'index.html')
    try:
        with open(template_path, 'r') as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Dashboard not found</h1>"

@app.get("/health", response_model=HealthResponse)
def health():
    boot_time = psutil.boot_time()
    uptime_hours = (time.time() - boot_time) / 3600
    net = psutil.net_io_counters()
    return {
        "cpu": psutil.cpu_percent(interval=1),
        "ram": psutil.virtual_memory().percent,
        "disk": get_host_disk_usage(),
        "uptime_hours": round(uptime_hours, 2),
        "net_sent_mb": round(net.bytes_sent / (1024 * 1024), 2),
        "net_recv_mb": round(net.bytes_recv / (1024 * 1024), 2),
        "timestamp": time.strftime('%Y-%m-%d %H:%M:%S')
    }

@app.get("/metrics/history")
def metrics_history(limit: int = 50):
    try:
        return get_history(limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/containers", response_model=list[ContainerResponse])
def containers():
    try:
        client = docker.from_env()
        result = []
        for c in client.containers.list(all=True):
            result.append({
                "name": c.name,
                "status": c.status,
                "image": c.image.tags[0] if c.image.tags else c.image.id,
                "id": c.id[:12],
                "created": c.attrs.get('Created', 'Unknown')
            })
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/containers/{container_name}/restart", response_model=RestartResponse)
def restart_container(container_name: str):
    try:
        client = docker.from_env()
        container = client.containers.get(container_name)
        container.restart()
        return {"message": f"Container {container_name} restarted", "success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/containers/{container_name}/start", response_model=RestartResponse)
def start_container(container_name: str):
    try:
        client = docker.from_env()
        container = client.containers.get(container_name)
        container.start()
        return {"message": f"Container {container_name} started", "success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/containers/{container_name}/stop", response_model=RestartResponse)
def stop_container(container_name: str):
    try:
        client = docker.from_env()
        container = client.containers.get(container_name)
        container.stop()
        return {"message": f"Container {container_name} stopped", "success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/logs")
def get_logs(lines: int = 100):
    try:
        with open("logs/autoops.log", "r") as f:
            all_lines = f.readlines()
        return [line.strip() for line in all_lines[-lines:]]
    except FileNotFoundError:
        return []

@app.post("/alert/test", response_model=TestAlertResponse)
def test_alert():
    success = send("AutoOps Engine test alert — system is working")
    return {"sent": success}

# --- Internal endpoints (called by monitor containers via HTTP) ---
from api.database import insert_metric

@app.post("/internal/push")
async def internal_push_metrics(data: dict):
    """Called by system_monitor container to push metrics into the API process."""
    cpu = data.get("cpu", 0.0)
    ram = data.get("ram", 0.0)
    disk = data.get("disk", 0.0)
    net_sent = data.get("net_sent_mb", 0.0)
    net_recv = data.get("net_recv_mb", 0.0)

    # AI anomaly detection (disabled)
    anomaly_score = 0.0
    is_anomaly = False

    # DB insert
    insert_metric(cpu, ram, disk, net_sent, net_recv, anomaly_score)

    # Prometheus gauges
    update_prometheus_metrics(cpu, ram, disk, anomaly_score)

    # WebSocket broadcast
    ts = time.strftime('%H:%M:%S')
    ws_data = {
        "type": "metrics",
        "cpu": cpu, "ram": ram, "disk": disk,
        "timestamp": ts,
        "anomaly": is_anomaly,
        "anomaly_score": anomaly_score
    }
    await manager.broadcast(ws_data)

    return {"ok": True}

@app.post("/internal/containers")
async def internal_push_containers(data: dict):
    """Called by docker_monitor container to push container status via WebSocket."""
    containers_list = data.get("containers", [])

    # Update Prometheus gauges
    if prometheus_available:
        container_total.set(len(containers_list))
        running = sum(1 for c in containers_list if c.get("status") == "running")
        container_up.set(running)

    # WebSocket broadcast
    await manager.broadcast({"type": "containers", "containers": containers_list})

    return {"ok": True}

@app.post("/internal/alert")
async def internal_alert(data: dict):
    """Called by monitor containers to send custom Telegram alerts."""
    msg = data.get("message")
    if msg:
        send(msg)
    return {"ok": True}

# Multi-Server SSH Endpoints
@app.post("/servers")
def add_server(server: ServerCreate):
    try:
        server_id = insert_server(server.name, server.host, server.port, server.username, server.ssh_key_path, server.password)
        new_server = get_server(server_id)
        test_result = {"success": False, "error": "SSHAgent not available"}
        if SSHAgent:
            agent = SSHAgent(server.host, server.port, server.username, server.ssh_key_path, server.password)
            test_result = agent.test_connection()
        # Persist connection result to DB
        import time as _time
        if test_result.get("success"):
            update_server_status(server_id, "online", _time.strftime('%Y-%m-%d %H:%M:%S'))
        else:
            update_server_status(server_id, "offline", _time.strftime('%Y-%m-%d %H:%M:%S'))
        new_server = get_server(server_id)  # re-fetch with updated status
        return {"server": new_server, "test": test_result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/servers")
def get_servers():
    try:
        return get_all_servers()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/servers/{server_id}")
def get_server_by_id(server_id: int):
    try:
        return get_server(server_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/servers/{server_id}")
def delete_server_by_id(server_id: int):
    try:
        delete_server(server_id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/servers/{server_id}/metrics")
def get_server_metrics(server_id: int, limit: int = 50):
    try:
        return get_remote_history(server_id, limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/servers/{server_id}/live-metrics")
def get_server_live_metrics(server_id: int):
    """SSH into the remote server, collect live metrics, persist to DB, and return them."""
    try:
        server = get_server(server_id)
        if not server:
            raise HTTPException(status_code=404, detail="Server not found")
        if not SSHAgent:
            raise HTTPException(status_code=501, detail="SSHAgent not loaded")

        agent = SSHAgent(
            server["host"], server["port"], server["username"],
            server["ssh_key_path"], server["password"]
        )
        metrics = agent.collect_metrics()

        ts = time.strftime('%Y-%m-%d %H:%M:%S')
        if metrics["reachable"]:
            update_server_status(server_id, "online", ts)
            # Persist to remote_metrics history
            from api.database import insert_remote_metric
            insert_remote_metric(
                server_id,
                metrics["cpu"], metrics["ram"],
                metrics["disk"], metrics["uptime_hours"]
            )
        else:
            update_server_status(server_id, "offline", ts)

        return {
            "server_id": server_id,
            "name": server["name"],
            "host": server["host"],
            "reachable": metrics["reachable"],
            "cpu": round(metrics["cpu"], 1),
            "ram": round(metrics["ram"], 1),
            "disk": round(metrics["disk"], 1),
            "uptime_hours": round(metrics["uptime_hours"], 2),
            "timestamp": ts,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/servers/{server_id}/test")
def test_server_connection(server_id: int):
    try:
        server = get_server(server_id)
        if not server:
            raise HTTPException(status_code=404, detail="Server not found")
        if not SSHAgent:
            return {"success": False, "error": "SSHAgent not loaded"}
        agent = SSHAgent(server["host"], server["port"], server["username"], server["ssh_key_path"], server["password"])
        result = agent.test_connection()
        # Persist connection result
        import time as _time
        if result.get("success"):
            update_server_status(server_id, "online", _time.strftime('%Y-%m-%d %H:%M:%S'))
        else:
            update_server_status(server_id, "offline", _time.strftime('%Y-%m-%d %H:%M:%S'))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/servers/{server_id}/key-info")
def get_key_info(server_id: int):
    """Return public key info and ssh-copy-id command for setting up key-based auth.

    Searches for public keys in multiple locations to work both inside Docker
    (where ~/.ssh is mounted at /home/autoops/.ssh) and when run natively.
    """
    server = get_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    key_names = ["id_ed25519.pub", "id_rsa.pub", "id_ecdsa.pub", "id_dsa.pub"]

    # Build candidate search directories in priority order:
    # 1. The mounted host ~/.ssh (docker-compose mounts ~/.ssh -> /home/autoops/.ssh)
    # 2. Any user home found under /host/home (host filesystem via bind mount)
    # 3. Standard expanduser fallback (works when running natively)
    search_dirs = [
        "/home/autoops/.ssh",          # docker-compose mount target
        os.path.expanduser("~/.ssh"),  # native / non-docker run
    ]

    # Add every user home under the host /host/home mount
    host_home = "/host/home"
    if os.path.isdir(host_home):
        try:
            for user_dir in os.listdir(host_home):
                candidate = os.path.join(host_home, user_dir, ".ssh")
                if os.path.isdir(candidate):
                    search_dirs.append(candidate)
        except PermissionError:
            pass

    pub_key = None
    pub_key_path = None
    for ssh_dir in search_dirs:
        for key_name in key_names:
            candidate = os.path.join(ssh_dir, key_name)
            if os.path.isfile(candidate):
                try:
                    with open(candidate) as f:
                        content = f.read().strip()
                    if content:
                        pub_key = content
                        pub_key_path = candidate
                        break
                except PermissionError:
                    continue
        if pub_key:
            break

    # Build the ssh-copy-id command using the host-side key path
    # (strip /host prefix or resolve container-mount path -> real host path)
    display_key_path = pub_key_path
    if pub_key_path:
        if pub_key_path.startswith("/host/home/"):
            # Already from /host bind-mount — strip the /host prefix
            display_key_path = pub_key_path[len("/host"):]  # /home/user/.ssh/key.pub
        elif pub_key_path.startswith("/home/autoops/.ssh/"):
            # Mounted from host's ~/.ssh into the container. Find the real host user
            # by checking which /host/home/<user>/.ssh/ contains the same key name.
            key_basename = os.path.basename(pub_key_path)
            host_match = None
            host_home = "/host/home"
            if os.path.isdir(host_home):
                try:
                    for user in os.listdir(host_home):
                        candidate = os.path.join(host_home, user, ".ssh", key_basename)
                        if os.path.isfile(candidate):
                            host_match = f"/home/{user}/.ssh/{key_basename}"
                            break
                except PermissionError:
                    pass
            display_key_path = host_match or pub_key_path


    cmd = (
        f"ssh-copy-id -i {display_key_path} -p {server['port']} {server['username']}@{server['host']}"
        if display_key_path else None
    )
    return {
        "public_key": pub_key,
        "public_key_path": display_key_path,
        "ssh_copy_id_cmd": cmd,
        "server": {"host": server["host"], "port": server["port"], "username": server["username"]}
    }


# Security Scanner Endpoints
executor = ThreadPoolExecutor(max_workers=2)

@app.post("/security/scan")
async def run_security_scan():
    try:
        if not scanner:
            raise HTTPException(status_code=501, detail="Security scanner module not loaded")
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(executor, scanner.run_full_scan)
        
        insert_scan_result(
            result["scan_time"],
            json.dumps(result),
            result["summary"]["critical_count"],
            result["summary"]["warning_count"],
            result["summary"]["overall_risk"]
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/security/results")
def get_security_results():
    try:
        latest = get_latest_scan()
        if not latest:
            return {"message": "No scan results yet. POST /security/scan"}
        return json.loads(latest["results_json"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/security/history")
def get_sec_history():
    try:
        return get_scan_history(10)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/security/quick")
async def quick_security_scan():
    try:
        if not scanner:
            raise HTTPException(status_code=501, detail="Security scanner module not loaded")
        loop = asyncio.get_event_loop()
        ports = await loop.run_in_executor(executor, scanner.scan_open_ports)
        return ports
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
