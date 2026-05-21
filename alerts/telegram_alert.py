# FILE: alerts/telegram_alert.py
import os
import requests
import logging
from dotenv import load_dotenv

load_dotenv()

TOKEN  = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send(message: str, parse_mode: str = "Markdown") -> bool:
    """Send a Telegram message. parse_mode defaults to Markdown for bold/code formatting."""
    if not TOKEN or not CHAT_ID or "your_telegram" in TOKEN:
        logging.warning("Telegram skipped: Token or Chat ID not configured.")
        return False

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": parse_mode,
    }

    try:
        # Update Prometheus counter (best-effort)
        try:
            from api.main import alert_counter
            alert_type = "info"
            if any(k in message for k in ("CRITICAL", "HIGH", "UNREACHABLE", "ALERT")):
                alert_type = "critical"
            elif any(k in message for k in ("exited", "ANOMALY", "⚠️")):
                alert_type = "warning"
            alert_counter.labels(alert_type=alert_type).inc()
        except Exception:
            pass

        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        return True
    except Exception as e:
        logging.error(f"Telegram send failed: {e}")
        return False
