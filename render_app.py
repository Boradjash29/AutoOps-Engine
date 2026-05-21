# FILE: render_app.py
# Unified entry point for Render.com deployment.
# Combines FastAPI API + Flask Dashboard + System Monitor into a single process
# (Render free tier only supports one container)

import threading
import time
import os
import sys
import psutil
import logging

# Setup logging to stdout for Render
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("AutoOps")

# Ensure logs directory exists
os.makedirs("logs", exist_ok=True)

# ---- Background System Monitor Thread ----
def system_monitor_thread():
    """Collects system metrics and pushes them to the API (localhost since same process)."""
    import requests
    time.sleep(5)  # Wait for API to start
    API_URL = "http://127.0.0.1:8000"
    while True:
        try:
            cpu = psutil.cpu_percent(interval=1)
            ram = psutil.virtual_memory().percent
            disk = psutil.disk_usage('/').percent
            net = psutil.net_io_counters()
            sent_mb = round(net.bytes_sent / (1024 * 1024), 2)
            recv_mb = round(net.bytes_recv / (1024 * 1024), 2)

            payload = {
                "cpu": cpu, "ram": ram, "disk": disk,
                "net_sent_mb": sent_mb, "net_recv_mb": recv_mb
            }
            try:
                requests.post(f"{API_URL}/internal/push", json=payload, timeout=5)
            except Exception:
                pass

            logger.info(f"Stats: CPU {cpu}% | RAM {ram}% | Disk {disk}%")
        except Exception as e:
            logger.error(f"Monitor error: {e}")
        time.sleep(15)

# ---- Background Flask Dashboard Thread ----
def dashboard_thread():
    """Runs the Flask dashboard on port 5000."""
    from dashboard.app import app as flask_app
    flask_app.run(host='0.0.0.0', port=5000, use_reloader=False)

# ---- Start Background Threads ----
def start_background_services():
    monitor = threading.Thread(target=system_monitor_thread, daemon=True)
    monitor.start()
    logger.info("✅ System Monitor thread started")

    dashboard = threading.Thread(target=dashboard_thread, daemon=True)
    dashboard.start()
    logger.info("✅ Dashboard thread started on port 5000")

# Start threads when this module loads (before uvicorn serves the API)
start_background_services()

# ---- Import and expose the FastAPI app for uvicorn ----
from api.main import app
