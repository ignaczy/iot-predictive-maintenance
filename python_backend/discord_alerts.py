import os
import time
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configuration variables loaded from environment
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
REQUIRED_ANOMALY_DURATION = int(os.getenv("REQUIRED_ANOMALY_DURATION", 10))  # in seconds
ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", 60))

# State variables
_anomaly_start_time = None
_last_alert_time = 0


def send_discord_alert(data: dict, health_score: int, is_anomaly: bool) -> bool:
    """Sends a simplified alert to Discord in case of a persistent anomaly."""
    global _anomaly_start_time, _last_alert_time
    current_time = time.time()

    # Ensure Webhook URL is configured
    if not DISCORD_WEBHOOK_URL:
        print("[DISCORD] ❌ Error: DISCORD_WEBHOOK_URL is not set in .env file.")
        return False

    # Reset state if the anomaly has stopped
    if not is_anomaly:
        if _anomaly_start_time is not None:
            print("[DISCORD] Status back to normal. Resetting timer.")
            _anomaly_start_time = None
        return False

    # Initialize detection timestamp
    if _anomaly_start_time is None:
        _anomaly_start_time = current_time
        print(f"[DISCORD] Anomaly detected. Verifying ({REQUIRED_ANOMALY_DURATION}s)...")
        return False

    anomaly_duration = current_time - _anomaly_start_time

    # Check timing conditions and cooldown
    if anomaly_duration < REQUIRED_ANOMALY_DURATION:
        return False

    if current_time - _last_alert_time < ALERT_COOLDOWN_SECONDS:
        return False

    # Simplified message payload (Embed)
    payload = {
        "username": "System Predictor ML",
        "avatar_url": "https://cdn-icons-png.flaticon.com/512/1087/1087815.png",
        "embeds": [
            {
                "title": "🚨 Anomaly Detected",
                "color": 15158332,  # Red
                "fields": [
                    {
                        "name": "Health Score",
                        "value": f"**{health_score}%**",
                        "inline": True
                    },
                    {
                        "name": "Vibration (RMS)",
                        "value": f"`{data.get('acc_rms', 0):.2f} m/s²`",
                        "inline": True
                    },
                    {
                        "name": "Temperature",
                        "value": f"`{data.get('temperature', 0):.1f} °C`",
                        "inline": True
                    }
                ],
                "footer": {
                    "text": f"Duration: {int(anomaly_duration)}s"
                }
            }
        ]
    }

    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=5)
        if response.status_code in (200, 204):
            print("[DISCORD] ✅ Alert sent!")
            _last_alert_time = current_time
            return True
        else:
            print(f"[DISCORD] ❌ HTTP Error: {response.status_code}")
            return False
    except Exception as e:
        print(f"[DISCORD] ❌ Connection error: {e}")
        return False