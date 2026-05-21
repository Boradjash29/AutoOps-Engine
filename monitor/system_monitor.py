# FILE: monitor/system_monitor.py
import time
import psutil
import os
import sys
import logging
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Setup logging
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/autoops.log",
    level=logging.INFO,
    format='%(asctime)s - MONITOR - %(message)s'
)

CPU_THRESH = float(os.getenv("CPU_THRESHOLD", "80"))
RAM_THRESH = float(os.getenv("RAM_THRESHOLD", "85"))
DISK_THRESH = float(os.getenv("DISK_THRESHOLD", "85"))

API_URL = "http://api:8000"

def collect():
    while True:
        try:
            cpu = psutil.cpu_percent(interval=1)
            ram = psutil.virtual_memory().percent
            disk = psutil.disk_usage('/').percent
            net = psutil.net_io_counters()
            sent_mb = round(net.bytes_sent / (1024 * 1024), 2)
            recv_mb = round(net.bytes_recv / (1024 * 1024), 2)

            payload = {
                "cpu": cpu,
                "ram": ram,
                "disk": disk,
                "net_sent_mb": sent_mb,
                "net_recv_mb": recv_mb
            }

            # POST to the API — it handles DB, WebSocket, Prometheus, and anomaly detection
            try:
                resp = requests.post(f"{API_URL}/internal/push", json=payload, timeout=5)
                if resp.status_code != 200:
                    logging.warning(f"API push returned {resp.status_code}: {resp.text}")
            except Exception as e:
                logging.error(f"Failed to push metrics to API: {e}")

            logging.info(f"Stats: CPU {cpu}% | RAM {ram}% | Disk {disk}%")

        except Exception as e:
            logging.error(f"System monitor error: {e}")

        time.sleep(10)

if __name__ == "__main__":
    logging.info("Starting System Monitor...")
    collect()
