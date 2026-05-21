# FILE: monitor/docker_monitor.py
import docker
import time
import os
import sys
import logging
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/autoops.log",
    level=logging.INFO,
    format='%(asctime)s - DOCKER - %(message)s'
)

API_URL = "http://api:8000"

def monitor_containers():
    try:
        client = docker.from_env()
    except Exception as e:
        logging.error(f"Cannot connect to Docker daemon: {e}")
        time.sleep(10)
        return

    previous_states = {}

    while True:
        try:
            containers = client.containers.list(all=True)
            current_states = {c.name: c.status for c in containers}

            ws_containers = []

            for c in containers:
                name = c.name
                status = c.status
                ws_containers.append({
                    "name": name,
                    "status": status,
                    "image": c.image.tags[0] if c.image.tags else c.image.id,
                    "id": c.id[:12]
                })

                prev_status = previous_states.get(name)

                if status == 'exited' and prev_status == 'running':
                    logging.warning(f"Container {name} crashed. Attempting restart...")
                    
                    try:
                        requests.post(f"{API_URL}/internal/alert", json={
                            "message": f"🚨 *CONTAINER CRASH DETECTED* 🚨\n\n*Name:* {name}\n*Image:* {c.image.tags[0] if c.image.tags else c.image.id}\n*Status:* Exited Unexpectedly\n\nAttempting automatic restart..."
                        }, timeout=5)
                    except Exception as alert_err:
                        logging.error(f"Failed to send crash alert: {alert_err}")

                    try:
                        c.restart()
                        logging.info(f"Successfully restarted {name}")
                        try:
                            requests.post(f"{API_URL}/internal/alert", json={
                                "message": f"✅ *RESTART SUCCESSFUL* ✅\n\nContainer `{name}` was successfully recovered by AutoOps Engine."
                            }, timeout=5)
                        except:
                            pass
                    except Exception as e:
                        logging.error(f"Failed to restart {name}: {e}")
                        try:
                            requests.post(f"{API_URL}/internal/alert", json={
                                "message": f"❌ *RESTART FAILED* ❌\n\nContainer `{name}` could not be restarted. Manual intervention required.\nError: {str(e)}"
                            }, timeout=5)
                        except:
                            pass

            previous_states = current_states

            # Push container data to API for WebSocket broadcast
            try:
                payload = {
                    "type": "containers",
                    "containers": ws_containers
                }
                requests.post(f"{API_URL}/internal/containers", json=payload, timeout=5)
            except Exception as e:
                logging.error(f"Failed to push containers to API: {e}")

        except Exception as e:
            logging.error(f"Docker monitor error: {e}")

        time.sleep(15)

if __name__ == "__main__":
    logging.info("Starting Docker Monitor...")
    monitor_containers()
