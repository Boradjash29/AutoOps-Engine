# FILE: api/database.py
import sqlite3
import os
import time
import threading

DB_PATH = os.getenv("DB_PATH", "logs/metrics.db")
db_lock = threading.Lock()

def init_db():
    """Initialize the SQLite metrics and security tables."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with db_lock:
        with sqlite3.connect(DB_PATH, check_same_thread=False) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    cpu REAL,
                    ram REAL,
                    disk REAL,
                    net_sent_mb REAL,
                    net_recv_mb REAL,
                    anomaly_score REAL DEFAULT 0.0
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS servers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    host TEXT NOT NULL,
                    port INTEGER DEFAULT 22,
                    username TEXT NOT NULL,
                    ssh_key_path TEXT,
                    password TEXT,
                    added_at TEXT NOT NULL,
                    last_seen TEXT,
                    status TEXT DEFAULT 'unknown'
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS remote_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    cpu REAL,
                    ram REAL,
                    disk REAL,
                    uptime_hours REAL,
                    FOREIGN KEY (server_id) REFERENCES servers(id)
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS security_scans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scan_time TEXT NOT NULL,
                    results_json TEXT NOT NULL,
                    critical_count INTEGER,
                    warning_count INTEGER,
                    overall_risk TEXT
                )
            ''')
            conn.commit()

# --- System Metrics ---
def insert_metric(cpu, ram, disk, net_sent_mb, net_recv_mb, anomaly_score=0.0):
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    with db_lock:
        with sqlite3.connect(DB_PATH, check_same_thread=False) as conn:
            conn.execute(
                "INSERT INTO metrics (timestamp, cpu, ram, disk, net_sent_mb, net_recv_mb, anomaly_score) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ts, cpu, ram, disk, net_sent_mb, net_recv_mb, anomaly_score)
            )
            conn.commit()

def get_latest(n=1) -> list[dict]:
    with db_lock:
        with sqlite3.connect(DB_PATH, check_same_thread=False) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM metrics ORDER BY id DESC LIMIT ?", (n,)).fetchall()
            return [dict(row) for row in rows]

def get_history(limit=50) -> list[dict]:
    return get_latest(n=limit)

def get_anomaly_history(limit=100) -> list[dict]:
    with db_lock:
        with sqlite3.connect(DB_PATH, check_same_thread=False) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM metrics WHERE anomaly_score < 0 ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(row) for row in rows]

# --- SSH Servers ---
def insert_server(name, host, port, username, ssh_key_path, password) -> int:
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    with db_lock:
        with sqlite3.connect(DB_PATH, check_same_thread=False) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO servers (name, host, port, username, ssh_key_path, password, added_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, host, port, username, ssh_key_path, password, ts)
            )
            conn.commit()
            return cursor.lastrowid

def get_all_servers() -> list[dict]:
    with db_lock:
        with sqlite3.connect(DB_PATH, check_same_thread=False) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM servers").fetchall()
            return [dict(row) for row in rows]

def get_server(server_id: int) -> dict:
    with db_lock:
        with sqlite3.connect(DB_PATH, check_same_thread=False) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM servers WHERE id = ?", (server_id,)).fetchone()
            return dict(row) if row else {}

def delete_server(server_id: int):
    with db_lock:
        with sqlite3.connect(DB_PATH, check_same_thread=False) as conn:
            conn.execute("DELETE FROM remote_metrics WHERE server_id = ?", (server_id,))
            conn.execute("DELETE FROM servers WHERE id = ?", (server_id,))
            conn.commit()

def update_server_status(server_id: int, status: str, last_seen: str):
    with db_lock:
        with sqlite3.connect(DB_PATH, check_same_thread=False) as conn:
            conn.execute("UPDATE servers SET status = ?, last_seen = ? WHERE id = ?", (status, last_seen, server_id))
            conn.commit()

def insert_remote_metric(server_id, cpu, ram, disk, uptime_hours):
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    with db_lock:
        with sqlite3.connect(DB_PATH, check_same_thread=False) as conn:
            conn.execute(
                "INSERT INTO remote_metrics (server_id, timestamp, cpu, ram, disk, uptime_hours) VALUES (?, ?, ?, ?, ?, ?)",
                (server_id, ts, cpu, ram, disk, uptime_hours)
            )
            conn.commit()

def get_remote_history(server_id: int, limit=50) -> list[dict]:
    with db_lock:
        with sqlite3.connect(DB_PATH, check_same_thread=False) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM remote_metrics WHERE server_id = ? ORDER BY id DESC LIMIT ?", (server_id, limit)).fetchall()
            return [dict(row) for row in rows]

# --- Security Scanner ---
def insert_scan_result(scan_time, results_json, critical_count, warning_count, overall_risk):
    with db_lock:
        with sqlite3.connect(DB_PATH, check_same_thread=False) as conn:
            conn.execute(
                "INSERT INTO security_scans (scan_time, results_json, critical_count, warning_count, overall_risk) VALUES (?, ?, ?, ?, ?)",
                (scan_time, results_json, critical_count, warning_count, overall_risk)
            )
            conn.commit()

def get_latest_scan() -> dict:
    with db_lock:
        with sqlite3.connect(DB_PATH, check_same_thread=False) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM security_scans ORDER BY id DESC LIMIT 1").fetchone()
            return dict(row) if row else {}

def get_scan_history(limit=10) -> list[dict]:
    with db_lock:
        with sqlite3.connect(DB_PATH, check_same_thread=False) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT id, scan_time, critical_count, warning_count, overall_risk FROM security_scans ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(row) for row in rows]
