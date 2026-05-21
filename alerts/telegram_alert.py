# FILE: alerts/telegram_alert.py
import os
import requests
import logging
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send(message: str) -> bool:
    if not TOKEN or not CHAT_ID or "your_telegram" in TOKEN:
        logging.warning("Telegram alerts skipped: Token or Chat ID not configured properly.")
        return False
        
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }
    
    try:
        # Update Prometheus counter if possible
        try:
            from api.main import alert_counter
            alert_type = "info"
            if "CRITICAL" in message or "HIGH" in message or "UNREACHABLE" in message or "ALERT" in message:
                alert_type = "critical"
            elif "exited" in message or "ANOMALY" in message:
                alert_type = "warning"
            alert_counter.labels(alert_type=alert_type).inc()
        except Exception:
            pass
            
        # Non-blocking request with timeout
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        return True
    except Exception as e:
        logging.error(f"Telegram alert failed: {e}")
        return False
