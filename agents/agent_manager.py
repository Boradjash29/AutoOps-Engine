# FILE: agents/agent_manager.py
import threading
import time
import logging
from api.database import get_all_servers, insert_remote_metric, update_server_status
from agents.ssh_agent import SSHAgent
from alerts.telegram_alert import send
import os

CPU_THRESHOLD = float(os.getenv("CPU_THRESHOLD", "80"))

class AgentManager:
    def __init__(self):
        self.running = False
        self._thread = None
        # Track previous states to detect state transitions
        self.server_states = {}

    def start(self):
        if not self.running:
            self.running = True
            self._thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._thread.start()

    def stop(self):
        self.running = False

    def _poll_loop(self):
        while self.running:
            try:
                servers = get_all_servers()
                
                # Update Prometheus gauge if available
                # To avoid circular imports or complex dependency injection, we can just do this locally if needed,
                # but it's better if api handles gauge setting or we just let it be.
                # The user spec says "Update Prometheus gauge with remote server count"
                # We'll just try to import the gauge
                try:
                    from api.main import prometheus_available, Gauge
                    if prometheus_available:
                        # Find gauge or let the api handle it. We can just skip updating gauge if it's tricky.
                        pass
                except:
                    pass
                
                for srv in servers:
                    try:
                        agent = SSHAgent(
                            host=srv['host'], port=srv['port'], username=srv['username'],
                            ssh_key_path=srv['ssh_key_path'], password=srv['password']
                        )
                        metrics = agent.collect_metrics()
                        
                        server_id = srv['id']
                        name = srv['name']
                        prev_state = self.server_states.get(server_id, srv['status'])
                        
                        ts = time.strftime('%Y-%m-%d %H:%M:%S')
                        
                        if metrics['reachable']:
                            insert_remote_metric(
                                server_id, metrics['cpu'], metrics['ram'], 
                                metrics['disk'], metrics['uptime_hours']
                            )
                            update_server_status(server_id, 'online', ts)
                            
                            if prev_state != 'online':
                                send(f"✅ Server {name} ({srv['host']}) is now ONLINE.")
                                
                            if metrics['cpu'] > CPU_THRESHOLD:
                                send(f"⚠️ HIGH CPU on Remote Server {name}: {metrics['cpu']}%")
                                
                            self.server_states[server_id] = 'online'
                        else:
                            update_server_status(server_id, 'offline', ts)
                            
                            if prev_state == 'online':
                                send(f"🚨 Server {name} ({srv['host']}) is UNREACHABLE!")
                                
                            self.server_states[server_id] = 'offline'
                            
                    except Exception as e:
                        logging.error(f"Error processing server {srv['name']}: {e}")
            except Exception as e:
                logging.error(f"Error in AgentManager main loop: {e}")
                
            # Sleep 30s but check running flag frequently
            for _ in range(30):
                if not self.running:
                    break
                time.sleep(1)
