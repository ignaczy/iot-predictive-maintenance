-- 1. Create database (execute as superuser, e.g., postgres)
CREATE DATABASE industrial_monitoring;

-- Switch to the newly created database before running the code below:
-- \c industrial_monitoring

-- 2. Create 'features' table
CREATE TABLE IF NOT EXISTS features (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    machine_id INT NOT NULL,
    measurement_window INT NOT NULL,
    
    -- BME280 and VL53L0X sensor data
    temperature REAL,
    humidity REAL,
    pressure REAL,
    distance INT,
    
    -- Accelerometer time-domain statistics
    acc_rms REAL,
    acc_std REAL,
    acc_peak REAL,
    acc_p2p REAL,
    crest_factor REAL,
    skewness REAL,
    kurtosis REAL,
    
    -- FFT frequency-domain statistics
    fft_dom_freq REAL,
    fft_max_amp REAL,
    spectral_centroid REAL,
    
    -- Anomaly detection results (ML)
    health_score INT CHECK (health_score BETWEEN 0 AND 100),
    status_ok BOOLEAN NOT NULL
);

-- 3. Create indexes to optimize time and machine query performance
CREATE INDEX IF NOT EXISTS idx_features_created_at ON features(created_at);
CREATE INDEX IF NOT EXISTS idx_features_machine_id ON features(machine_id);