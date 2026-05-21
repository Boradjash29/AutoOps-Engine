# FILE: agents/ssh_agent.py
import paramiko
import time
import logging
import os


def _build_default_key_paths() -> list[str]:
    """Return all candidate private key paths, covering native and Docker environments."""
    key_names = ["id_ed25519", "id_rsa", "id_ecdsa", "id_dsa"]
    candidate_dirs = [
        "/home/autoops/.ssh",          # docker-compose mount: ~/.ssh -> /home/autoops/.ssh
        os.path.expanduser("~/.ssh"),  # native run
    ]
    # Also search /host/home/* (host FS bind-mounted at /host)
    host_home = "/host/home"
    if os.path.isdir(host_home):
        try:
            for user in os.listdir(host_home):
                d = os.path.join(host_home, user, ".ssh")
                if os.path.isdir(d):
                    candidate_dirs.append(d)
        except PermissionError:
            pass

    paths = []
    seen = set()
    for d in candidate_dirs:
        for name in key_names:
            p = os.path.join(d, name)
            if p not in seen:
                seen.add(p)
                paths.append(p)
    return paths


DEFAULT_KEY_PATHS = _build_default_key_paths()

SSH_TIMEOUT = 8  # seconds


class SSHAgent:
    def __init__(self, host: str, port: int, username: str,
                 ssh_key_path: str = None, password: str = None):
        self.host = host
        self.port = port
        self.username = username
        self.ssh_key_path = ssh_key_path
        self.password = password
        self.client = None
        self._last_error: str = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_client(self) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        return client

    def _try_key(self, client: paramiko.SSHClient, key_path: str) -> bool:
        """Attempt key-based auth. Supports RSA, Ed25519, ECDSA, DSS."""
        if not os.path.isfile(key_path):
            return False
        key_loaders = [
            paramiko.RSAKey.from_private_key_file,
            paramiko.Ed25519Key.from_private_key_file,
            paramiko.ECDSAKey.from_private_key_file,
            paramiko.DSSKey.from_private_key_file,
        ]
        for loader in key_loaders:
            try:
                key = loader(key_path)
                client.connect(
                    hostname=self.host, port=self.port, username=self.username,
                    pkey=key, timeout=SSH_TIMEOUT, allow_agent=False,
                    look_for_keys=False, banner_timeout=SSH_TIMEOUT
                )
                return True
            except paramiko.AuthenticationException:
                # Key loaded fine but auth was rejected — no point trying other loaders
                raise
            except Exception:
                continue  # wrong key type, try next loader
        return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """
        Try every available auth method in order:
          1. Explicit SSH key path (if provided)
          2. Default key files (~/.ssh/id_rsa, id_ed25519, …)
          3. Password (if provided)
        Sets self._last_error on failure.
        """
        self._last_error = None
        self.client = self._make_client()

        # 1. Explicit key
        if self.ssh_key_path:
            try:
                if self._try_key(self.client, self.ssh_key_path):
                    return True
            except paramiko.AuthenticationException as e:
                self._last_error = f"Key auth rejected: {e}"
                logging.warning(f"[SSHAgent] Key auth rejected for {self.host}: {e}")
                # Don't fall through to default keys — explicit key was specified
                return False
            except Exception as e:
                logging.warning(f"[SSHAgent] Key auth error for {self.host}: {e}. Trying password.")

        # 2. Default system keys (only when no explicit key was specified)
        if not self.ssh_key_path:
            for key_path in DEFAULT_KEY_PATHS:
                try:
                    self.client = self._make_client()
                    if self._try_key(self.client, key_path):
                        logging.info(f"[SSHAgent] Connected to {self.host} using {key_path}")
                        return True
                except paramiko.AuthenticationException:
                    logging.debug(f"[SSHAgent] Key {key_path} rejected by {self.host}")
                    continue
                except Exception:
                    continue

        # 3. Password
        if self.password:
            try:
                self.client = self._make_client()
                self.client.connect(
                    hostname=self.host, port=self.port, username=self.username,
                    password=self.password, timeout=SSH_TIMEOUT,
                    allow_agent=False, look_for_keys=False,
                    banner_timeout=SSH_TIMEOUT
                )
                return True
            except paramiko.AuthenticationException as e:
                self._last_error = f"Password auth rejected: {e}"
                logging.error(f"[SSHAgent] Password auth rejected for {self.host}: {e}")
                return False
            except Exception as e:
                self._last_error = str(e)
                logging.error(f"[SSHAgent] Connection failed to {self.host}: {e}")
                return False

        # No credentials at all
        self._last_error = "No authentication method provided (no key path, no password, and no default keys found)"
        logging.error(f"[SSHAgent] {self._last_error} for {self.host}")
        return False

    def disconnect(self):
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None

    def run_command(self, command: str) -> str:
        if not self.client:
            return ""
        try:
            _, stdout, _ = self.client.exec_command(command, timeout=15)
            return stdout.read().decode().strip()
        except Exception as e:
            logging.error(f"[SSHAgent] Command execution failed on {self.host}: {e}")
            return ""

    def collect_metrics(self) -> dict:
        result = {
            "reachable": False,
            "cpu": 0.0, "ram": 0.0, "disk": 0.0, "uptime_hours": 0.0
        }

        if not self.connect():
            return result

        try:
            cpu_out = self.run_command(
                "top -bn1 | grep 'Cpu(s)' | awk '{print $2 + $4}'"
            )
            if cpu_out:
                result["cpu"] = float(cpu_out)

            ram_out = self.run_command(
                "free | grep Mem | awk '{print $3/$2 * 100.0}'"
            )
            if ram_out:
                result["ram"] = float(ram_out)

            disk_out = self.run_command(
                "df / | awk 'NR==2 {print $5}' | tr -d '%'"
            )
            if disk_out:
                result["disk"] = float(disk_out)

            uptime_out = self.run_command(
                "awk '{print $1/3600}' /proc/uptime"
            )
            if uptime_out:
                result["uptime_hours"] = float(uptime_out)

            result["reachable"] = True
        except Exception as e:
            logging.error(f"[SSHAgent] Metrics collection failed for {self.host}: {e}")
        finally:
            self.disconnect()

        return result

    def test_connection(self) -> dict:
        """Test SSH connectivity. Returns success, latency, and a human-readable error."""
        start = time.time()
        try:
            success = self.connect()
            latency = round((time.time() - start) * 1000, 2)
            self.disconnect()
            return {
                "success": success,
                "latency_ms": latency if success else 0,
                "error": None if success else (self._last_error or "Connection failed"),
            }
        except Exception as e:
            return {
                "success": False,
                "latency_ms": 0,
                "error": str(e),
            }
