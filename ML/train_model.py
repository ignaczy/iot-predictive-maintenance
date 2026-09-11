import os
import joblib
import pandas as pd
import psycopg2
from dotenv import load_dotenv
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

# Load environment variables from .env file
load_dotenv()

# --- DATABASE CONFIGURATION ---
DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "industrial_monitoring"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "postgres"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
}

MACHINE_ID = int(os.getenv("MACHINE_ID", 1))


def load_data_from_db():
    """Fetches feature data from the PostgreSQL database."""
    conn = psycopg2.connect(**DB_CONFIG)
    # Removed distance from SQL query
    query = f"""
        SELECT 
            acc_rms, acc_std, acc_peak, acc_p2p, crest_factor, 
            skewness, kurtosis, fft_dom_freq, fft_max_amp, spectral_centroid,
            temperature, humidity, pressure
        FROM features
        WHERE machine_id = {MACHINE_ID}
    """
    df = pd.read_sql(query, conn)
    conn.close()
    return df


def train_anomaly_model():
    """Trains the Isolation Forest model and saves model and scaler artifacts."""
    print("📥 Fetching data from database...")
    df = load_data_from_db().dropna()

    if len(df) < 50:
        print("❌ Not enough data in the database to train the model.")
        return

    # Feature vector without 'distance' (13 features)
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
    X = df[feature_cols]

    print(
        f"🧠 Training Isolation Forest on {len(X)} samples with {len(feature_cols)} features..."
    )

    # 1. Feature scaling
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # 2. Isolation Forest training
    model = IsolationForest(
        n_estimators=100, contamination=0.05, random_state=42
    )
    model.fit(X_scaled)

    # 3. Save model and scaler
    joblib.dump(model, "anomaly_model.pkl")
    joblib.dump(scaler, "scaler.pkl")

    print("✅ Model and Scaler successfully saved!")


if __name__ == "__main__":
    train_anomaly_model()