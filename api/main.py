# FILE: api/main.py
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
import psutil
import docker
import time
import os
import sys
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from api.database import (init_db, get_history, insert_server, get_all_servers, 
                         get_server, delete_server, get_remote_history, 
                         get_anomaly_history, insert_scan_result, get_latest_scan, get_scan_history)
from api.models import (HealthResponse, ContainerResponse, RestartResponse, 
                       TestAlertResponse, CleanupPreviewResponse, ServerCreate,
                       AnomalyPrediction, ModelStatus, TrainResponse)
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

async def periodic_status_report():
    while True:
        try:
            await asyncio.sleep(600)  # 10 minutes
            cpu = psutil.cpu_percent(interval=1)
            ram = psutil.virtual_memory().percent
            disk = psutil.disk_usage('/').percent
            boot_time = psutil.boot_time()
            uptime_hours = round((time.time() - boot_time) / 3600, 2)
            
            client = docker.from_env()
            containers = client.containers.list(all=True)
            total_c = len(containers)
            running_c = sum(1 for c in containers if c.status == 'running')
            
            model_status = "Not Trained ⏳"
            if detector and detector.is_trained:
                model_status = "Trained & Active 🟢"

            report = (
                "📊 *AutoOps Engine - 10 Min Periodic Report*\n\n"
                f"💻 *CPU Usage:* {cpu}%\n"
                f"🧠 *RAM Usage:* {ram}%\n"
                f"💾 *Disk Usage:* {disk}%\n"
                f"⏱ *Uptime:* {uptime_hours} hours\n"
                f"🐳 *Containers:* {running_c}/{total_c} Running\n"
                f"🤖 *AI Model:* {model_status}\n\n"
                "System is operating normally. ✅"
            )
            send(report)
        except Exception as e:
            print(f"Error in periodic report: {e}")

@app.on_event("startup")
async def startup_event():
    init_db()
    if agent_manager:
        agent_manager.start()
    if trainer:
        trainer.start()
    asyncio.create_task(periodic_status_report())

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
        "disk": psutil.disk_usage('/').percent,
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
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail="Container not found")
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

    # AI anomaly detection
    anomaly_score = 0.0
    is_anomaly = False
    if detector:
        anom = detector.predict(cpu, ram, disk)
        anomaly_score = anom["score"]
        is_anomaly = anom["is_anomaly"]
        if is_anomaly:
            send(f"⚠️ ANOMALY DETECTED: CPU={cpu}% RAM={ram}% DISK={disk}% Score={anomaly_score:.3f}")

    # DB insert
    insert_metric(cpu, ram, disk, net_sent, net_recv, anomaly_score)

    # Prometheus gauges
    update_prometheus_metrics(cpu, ram, disk, anomaly_score)

    # Threshold alerts
    cpu_thresh = float(os.getenv("CPU_THRESHOLD", "80"))
    ram_thresh = float(os.getenv("RAM_THRESHOLD", "85"))
    disk_thresh = float(os.getenv("DISK_THRESHOLD", "85"))
    if cpu > cpu_thresh:
        send(f"⚠️ HIGH CPU ALERT: {cpu}%")
    if ram > ram_thresh:
        send(f"⚠️ HIGH RAM ALERT: {ram}%")
    if disk > disk_thresh:
        send(f"⚠️ HIGH DISK ALERT: {disk}%")

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

@app.post("/servers/{server_id}/test")
def test_server_connection(server_id: int):
    try:
        server = get_server(server_id)
        if not server:
            raise HTTPException(status_code=404, detail="Server not found")
        if not SSHAgent:
            return {"success": False, "error": "SSHAgent not loaded"}
        agent = SSHAgent(server["host"], server["port"], server["username"], server["ssh_key_path"], server["password"])
        return agent.test_connection()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# AI Anomaly Detection Endpoints
@app.get("/anomalies/latest", response_model=AnomalyPrediction)
def latest_anomaly():
    try:
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage('/').percent
        if detector:
            result = detector.predict(cpu, ram, disk)
            result["cpu"] = cpu
            result["ram"] = ram
            result["disk"] = disk
            return result
        return {"is_anomaly": False, "score": 0.0, "confidence": 0.0, "cpu": cpu, "ram": ram, "disk": disk}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/anomalies/history")
def anomaly_history():
    try:
        return get_anomaly_history(100)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/anomalies/train", response_model=TrainResponse)
def train_model():
    try:
        if not detector:
            return {"trained": False, "samples_used": 0, "message": "AI module not loaded"}
        data = get_history(2000)
        success = detector.train(data)
        if success:
            detector.save()
            return {"trained": True, "samples_used": len(data), "message": "Model retrained successfully"}
        else:
            return {"trained": False, "samples_used": len(data), "message": "Insufficient data"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/anomalies/model/status", response_model=ModelStatus)
def model_status():
    try:
        if not detector:
            return {"is_trained": False, "model_path_exists": False, "contamination": 0.05, "n_estimators": 100}
        return {
            "is_trained": detector.is_trained,
            "model_path_exists": os.path.exists("logs/anomaly_model.pkl"),
            "contamination": detector.model.contamination,
            "n_estimators": detector.model.n_estimators
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
