import json
import os
import joblib
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
import pandas as pd
import psycopg2
from dotenv import load_dotenv
from discord_alerts import send_discord_alert

# Ładowanie zmiennych środowiskowych z pliku .env
load_dotenv()

# --- DATABASE CONFIGURATION ---
DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "industrial_monitoring"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "postgres"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
}

# --- MQTT CONFIGURATION ---
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "factory/machine1/telemetry")

MACHINE_ID = int(os.getenv("MACHINE_ID", 1))
MEASUREMENT_WINDOW = int(os.getenv("MEASUREMENT_WINDOW", 512))

# --- LOADING ML MODEL AND SCALER ---
APP_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.abspath(
    os.path.join(APP_DIR, "..", "ML", "anomaly_model.pkl")
)
SCALER_PATH = os.path.abspath(os.path.join(APP_DIR, "..", "ML", "scaler.pkl"))

ml_model = None
scaler = None

# Load model
if os.path.exists(MODEL_PATH):
    try:
        ml_model = joblib.load(MODEL_PATH)
        print(f"✅ [ML] Model successfully loaded from: {MODEL_PATH}")
    except Exception as e:
        print(f"❌ [ML] Error loading model: {e}")
else:
    print(f"⚠️ [ML] Warning: Model not found at path: {MODEL_PATH}")

# Load scaler
if os.path.exists(SCALER_PATH):
    try:
        scaler = joblib.load(SCALER_PATH)
        print(f"✅ [ML] Scaler successfully loaded from: {SCALER_PATH}")
    except Exception as e:
        print(f"❌ [ML] Error loading scaler: {e}")
else:
    print(f"⚠️ [ML] Warning: Scaler not found at path: {SCALER_PATH}")


def predict_anomaly(data):
    """Processes a sample through Scaler and Isolation Forest, calculating Health Score (%) and Status (OK/Anomaly)."""
    if ml_model is None or scaler is None:
        return 100, True  # Default to 100% health and OK if models are missing

    try:
        # 13 features used during training (EXACT ORDER WITHOUT 'distance')
        feature_cols = [
            "acc_rms",
            "acc_std",
            "acc_peak",
            "acc_p2p",
            "crest_factor",
            "skewness",
            "kurtosis",
            "fft_dom_freq",
            "fft_max_amp",
            "spectral_centroid",
            "temperature",
            "humidity",
            "pressure",
        ]

        # Create DataFrame for a single sample
        sample = pd.DataFrame([{col: data.get(col, 0.0) for col in feature_cols}])

        # 1. Feature normalization using loaded Scaler
        sample_scaled = scaler.transform(sample)

        # 2. Prediction using scaled data (1 = OK, -1 = Anomaly)
        pred = ml_model.predict(sample_scaled)[0]
        decision = ml_model.decision_function(sample_scaled)[0]

        # Linear mapping of decision_function [-0.2, +0.2] to 0-100% range
        normalized_score = (decision + 0.2) / 0.4
        health_score = int(max(0, min(100, normalized_score * 100)))
        status_ok = bool(pred == 1)

        return health_score, status_ok

    except Exception as e:
        print(f"[ML ERROR] Failed to process sample: {e}")
        return 100, True


def save_to_db(data, health_score, status_ok):
    """Saves the complete feature vector along with ML results to the database (including raw distance)."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()

        query = """
            INSERT INTO features 
            (machine_id, measurement_window, temperature, humidity, pressure, distance, 
             acc_rms, acc_std, acc_peak, acc_p2p, crest_factor, skewness, kurtosis, 
             fft_dom_freq, fft_max_amp, spectral_centroid, health_score, status_ok) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        values = (
            MACHINE_ID,
            MEASUREMENT_WINDOW,
            data.get("temperature"),
            data.get("humidity"),
            data.get("pressure"),
            data.get("distance"),  # Saved to DB even though ML doesn't use it
            data.get("acc_rms"),
            data.get("acc_std"),
            data.get("acc_peak"),
            data.get("acc_p2p"),
            data.get("crest_factor"),
            data.get("skewness"),
            data.get("kurtosis"),
            data.get("fft_dom_freq"),
            data.get("fft_max_amp"),
            data.get("spectral_centroid"),
            health_score,
            status_ok,
        )

        cur.execute(query, values)
        conn.commit()

        cur.close()
        conn.close()

        status_str = "OK" if status_ok else "⚠️ ANOMALY!"
        print(
            f"[DB Edge] Saved: RMS={data.get('acc_rms', 0):.2f} g | "
            f"Health Score={health_score}% | Status={status_str}"
        )
    except Exception as e:
        print(f"[DB ERROR] Failed to save to features table: {e}")


def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        print("[MQTT] Connected to broker!")
        client.subscribe(MQTT_TOPIC)
    else:
        print(f"[MQTT] Connection error to broker, code: {reason_code}")


def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode("utf-8")
        data = json.loads(payload)

        # 1. ML inference using scaled 13-element vector
        health_score, status_ok = predict_anomaly(data)

        # 2. Save to database
        save_to_db(data, health_score, status_ok)

        # 3. Trigger Discord alert (with time verification logic)
        is_anomaly = not status_ok
        send_discord_alert(data, health_score, is_anomaly)

    except json.JSONDecodeError:
        print("[MQTT ERROR] Received message is not valid JSON.")
    except Exception as e:
        print(f"[MQTT ERROR] Problem processing message: {e}")


if __name__ == "__main__":
    client = mqtt.Client(CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    print("[START] Connecting to MQTT broker...")
    client.connect(MQTT_BROKER, MQTT_PORT, 60)

    client.loop_forever()