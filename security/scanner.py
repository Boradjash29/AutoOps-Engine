# FILE: security/scanner.py
import socket
import docker
import os
import stat
import time
import logging
from alerts.telegram_alert import send

COMMON_PORTS = {
    21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP",
    80: "HTTP", 443: "HTTPS", 3306: "MySQL", 5432: "PostgreSQL",
    6379: "Redis", 27017: "MongoDB", 8080: "HTTP-Alt",
    8000: "AutoOps-API", 5000: "AutoOps-Dashboard",
    9090: "Prometheus", 3000: "Grafana"
}

class SecurityScanner:
    
    def scan_open_ports(self, host: str = "127.0.0.1", timeout: float = 0.5) -> list[dict]:
        open_ports = []
        socket.setdefaulttimeout(timeout)
        
        for port, service in COMMON_PORTS.items():
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    result = sock.connect_ex((host, port))
                    if result == 0:
                        risk = "info"
                        if port in [21, 23]:
                            risk = "critical"
                        elif port in [3306, 5432, 6379, 27017]:
                            risk = "warning"
                            
                        open_ports.append({
                            "port": port,
                            "service": service,
                            "risk": risk
                        })
            except (ConnectionRefusedError, socket.timeout):
                pass
            except Exception as e:
                logging.error(f"Port scan error on port {port}: {e}")
                
        return open_ports

    def scan_root_containers(self) -> list[dict]:
        root_containers = []
        try:
            client = docker.from_env()
            for container in client.containers.list():
                user = container.attrs.get('Config', {}).get('User', '')
                is_root = user in ["", "0", "root"]
                root_containers.append({
                    "name": container.name,
                    "image": container.image.tags[0] if container.image.tags else container.image.id,
                    "running_as_root": is_root,
                    "user": user if user else "root (default)"
                })
        except Exception as e:
            logging.warning(f"Docker unavailable during root scan: {e}")
            
        return root_containers

    def scan_world_writable_files(self, paths: list[str] = None) -> list[dict]:
        if not paths:
            paths = ["/etc", "/tmp", "/var/log"]
            
        writable_files = []
        count = 0
        
        for base_path in paths:
            if not os.path.exists(base_path):
                continue
            for root, dirs, files in os.walk(base_path):
                for name in files:
                    file_path = os.path.join(root, name)
                    try:
                        st = os.stat(file_path)
                        if st.st_mode & 0o002:  # Check world-writable bit
                            writable_files.append({
                                "path": file_path,
                                "permissions": oct(st.st_mode),
                                "risk": "high"
                            })
                            count += 1
                            if count >= 50:
                                return writable_files
                    except PermissionError:
                        pass
                    except Exception as e:
                        pass
        return writable_files

    def scan_ssh_config(self) -> list[dict]:
        issues = []
        ssh_config_path = "/etc/ssh/sshd_config"
        
        if not os.path.exists(ssh_config_path):
            return issues
            
        try:
            with open(ssh_config_path, "r") as f:
                lines = f.readlines()
                
            for line in lines:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                    
                if "PermitRootLogin yes" in line:
                    issues.append({
                        "setting": "PermitRootLogin",
                        "value": "yes",
                        "risk": "critical",
                        "recommendation": "Set to 'no' or 'prohibit-password'"
                    })
                elif "PasswordAuthentication yes" in line:
                    issues.append({
                        "setting": "PasswordAuthentication",
                        "value": "yes",
                        "risk": "warning",
                        "recommendation": "Set to 'no' and use SSH keys"
                    })
                elif "PermitEmptyPasswords yes" in line:
                    issues.append({
                        "setting": "PermitEmptyPasswords",
                        "value": "yes",
                        "risk": "critical",
                        "recommendation": "Set to 'no'"
                    })
                elif "Protocol 1" in line:
                    issues.append({
                        "setting": "Protocol",
                        "value": "1",
                        "risk": "critical",
                        "recommendation": "Set to '2'"
                    })
        except Exception:
            pass
            
        return issues

    def run_full_scan(self) -> dict:
        scan_time = time.strftime('%Y-%m-%d %H:%M:%S')
        
        open_ports = self.scan_open_ports()
        root_containers = self.scan_root_containers()
        world_writable = self.scan_world_writable_files()
        ssh_issues = self.scan_ssh_config()
        
        critical = 0
        warning = 0
        info = 0
        
        for p in open_ports:
            if p["risk"] == "critical": critical += 1
            elif p["risk"] == "warning": warning += 1
            else: info += 1
            
        for c in root_containers:
            if c["running_as_root"]: warning += 1
            
        for w in world_writable:
            critical += 1
            
        for s in ssh_issues:
            if s["risk"] == "critical": critical += 1
            elif s["risk"] == "warning": warning += 1
            
        overall = "ok"
        if critical > 0: overall = "critical"
        elif warning > 0: overall = "warning"
        
        result = {
            "scan_time": scan_time,
            "open_ports": open_ports,
            "root_containers": root_containers,
            "world_writable_files": world_writable,
            "ssh_config_issues": ssh_issues,
            "summary": {
                "critical_count": critical,
                "warning_count": warning,
                "info_count": info,
                "overall_risk": overall
            }
        }
        
        logging.info(f"Security scan completed. Risk: {overall.upper()}")
        
        if overall == "critical":
            send(f"🚨 SECURITY ALERT: {critical} critical issues found! Check /security/results")
            
        return result
