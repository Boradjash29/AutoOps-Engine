# FILE: agents/ssh_agent.py
import paramiko
import time
import logging

class SSHAgent:
    def __init__(self, host: str, port: int, username: str,
                 ssh_key_path: str = None, password: str = None):
        self.host = host
        self.port = port
        self.username = username
        self.ssh_key_path = ssh_key_path
        self.password = password
        self.client = None

    def connect(self) -> bool:
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            if self.ssh_key_path:
                try:
                    key = paramiko.RSAKey.from_private_key_file(self.ssh_key_path)
                    self.client.connect(
                        hostname=self.host, port=self.port, username=self.username,
                        pkey=key, timeout=10
                    )
                    return True
                except Exception as e:
                    logging.warning(f"Key auth failed for {self.host}: {e}. Trying password.")
            
            if self.password:
                self.client.connect(
                    hostname=self.host, port=self.port, username=self.username,
                    password=self.password, timeout=10
                )
                return True
                
            logging.error(f"No valid authentication method for {self.host}")
            return False
            
        except Exception as e:
            logging.error(f"SSH connection failed to {self.host}: {e}")
            return False

    def disconnect(self):
        if self.client:
            self.client.close()

    def run_command(self, command: str) -> str:
        if not self.client:
            return ""
        try:
            stdin, stdout, stderr = self.client.exec_command(command, timeout=10)
            return stdout.read().decode().strip()
        except Exception as e:
            logging.error(f"Command execution failed on {self.host}: {e}")
            return ""

    def collect_metrics(self) -> dict:
        result = {"reachable": False, "cpu": 0.0, "ram": 0.0, "disk": 0.0, "uptime_hours": 0.0}
        
        if not self.connect():
            return result
            
        try:
            # CPU
            cpu_out = self.run_command("top -bn1 | grep 'Cpu(s)' | awk '{print $2 + $4}'")
            if cpu_out:
                result["cpu"] = float(cpu_out)
                
            # RAM
            ram_out = self.run_command("free | grep Mem | awk '{print $3/$2 * 100.0}'")
            if ram_out:
                result["ram"] = float(ram_out)
                
            # DISK
            disk_out = self.run_command("df / | awk 'NR==2 {print $5}' | tr -d '%'")
            if disk_out:
                result["disk"] = float(disk_out)
                
            # UPTIME
            uptime_out = self.run_command("awk '{print $1/3600}' /proc/uptime")
            if uptime_out:
                result["uptime_hours"] = float(uptime_out)
                
            result["reachable"] = True
        except Exception as e:
            logging.error(f"Metrics collection failed for {self.host}: {e}")
        finally:
            self.disconnect()
            
        return result

    def test_connection(self) -> dict:
        start = time.time()
        success = self.connect()
        latency = (time.time() - start) * 1000 if success else 0
        self.disconnect()
        return {
            "success": success,
            "latency_ms": round(latency, 2),
            "error": None if success else "Connection failed"
        }
