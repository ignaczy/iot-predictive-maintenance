#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_BME280.h>
#include <Adafruit_VL53L0X.h>
#include <ArduinoJson.h>
#include "arduinoFFT.h"

// Hidden data
#include "secrets.h"

// --- NETWORK CONFIGURATION ---
const char* ssid = WIFI_SSID;
const char* password = WIFI_PASSWORD;
const char* mqtt_server = MQTT_SERVER;

WiFiClient espClient;
PubSubClient client(espClient);

// --- SENSOR HANDLING ---
Adafruit_MPU6050 mpu;
Adafruit_BME280 bme;
Adafruit_VL53L0X lox = Adafruit_VL53L0X();

// --- DSP AND FFT CONFIGURATION (EDGE COMPUTING) ---
#define SAMPLES 512            // Number of samples (must be a power of 2)
#define SAMPLING_FREQ_HZ 100   // Sampling at 100 Hz (10 ms per sample)

unsigned int sampling_period_us;
double vReal[SAMPLES];
double vImag[SAMPLES];

// FFT object initialization
ArduinoFFT<double> FFT = ArduinoFFT<double>(vReal, vImag, SAMPLES, SAMPLING_FREQ_HZ);

void setup_wifi() {
  Serial.print("Connecting to Wi-Fi...");
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nConnected to Wi-Fi!");
}

void reconnect() {
  while (!client.connected()) {
    Serial.print("Connecting to MQTT...");
    if (client.connect("ESP32_Condition_Monitoring")) {
      Serial.println(" Connected!");
    } else {
      Serial.print(" Failed, rc=");
      Serial.print(client.state());
      Serial.println(" Retrying in 5 seconds...");
      delay(5000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);

  // Calculation of the sampling period in microseconds (10,000 us = 10 ms)
  sampling_period_us = round(1000000.0 / SAMPLING_FREQ_HZ);

  // Sensor initialization
  if (!mpu.begin(0x68)) {
    Serial.println(" MPU6050 initialization failed!");
  } else {
    mpu.setAccelerometerRange(MPU6050_RANGE_2_G);
    mpu.setFilterBandwidth(MPU6050_BAND_44_HZ);
  }

  if (!bme.begin(0x76)) {
    Serial.println(" BME280 initialization failed!");
  }

  if (!lox.begin()) {
    Serial.println(" VL53L0X initialization failed!");
  }

  setup_wifi();
  client.setServer(mqtt_server, MQTT_PORT);
}

void loop() {
  if (!client.connected()) {
    reconnect();
  }
  client.loop();

  Serial.println("[DEBUG] 1. Starting MPU6050 sample collection...");

  // 1. ACCELEROMETER SAMPLES
  double sum_sq = 0;
  double min_val = 999.0;
  double max_val = -999.0;

  for (int i = 0; i < SAMPLES; i++) {
    unsigned long microseconds = micros();

    sensors_event_t a, g, temp;
    mpu.getEvent(&a, &g, &temp);

    double acc_total = sqrt(a.acceleration.x * a.acceleration.x +
                            a.acceleration.y * a.acceleration.y +
                            a.acceleration.z * a.acceleration.z);

    vReal[i] = acc_total;
    vImag[i] = 0.0;

    sum_sq += (acc_total * acc_total);
    if (acc_total < min_val) min_val = acc_total;
    if (acc_total > max_val) max_val = acc_total;

    while ((micros() - microseconds) < sampling_period_us) {
      // 10ms wait time
    }
  }

  double acc_rms = sqrt(sum_sq / SAMPLES);
  double acc_peak = max_val;
  double acc_p2p = max_val - min_val;
  double crest_factor = (acc_rms > 0.001) ? (acc_peak / acc_rms) : 0.0;

  Serial.println("[DEBUG] 2. MPU6050 collection completed. Calculating FFT...");

  // 2. STATISTICS AND FFT
  double mean_val = 0;
  for (int i = 0; i < SAMPLES; i++) mean_val += vReal[i];
  mean_val /= SAMPLES;

  double variance_sum = 0.0, skewness_sum = 0.0, kurtosis_sum = 0.0;

  for (int i = 0; i < SAMPLES; i++) {
    double diff = vReal[i] - mean_val;
    vReal[i] = diff;

    variance_sum += diff * diff;
    skewness_sum += diff * diff * diff;
    kurtosis_sum += diff * diff * diff * diff;
  }

  double variance = variance_sum / SAMPLES;
  double acc_std = sqrt(variance);

  double skewness = (acc_std > 0.0001) ? (skewness_sum / (SAMPLES * pow(acc_std, 3))) : 0.0;
  double kurtosis = (acc_std > 0.0001) ? (kurtosis_sum / (SAMPLES * pow(acc_std, 4))) : 0.0;

  FFT.windowing(FFTWindow::Hamming, FFTDirection::Forward);
  FFT.compute(FFTDirection::Forward);
  FFT.complexToMagnitude();

  double fft_dom_freq = FFT.majorPeak();
  double fft_max_amp = 0.0;
  double weighted_sum = 0.0;
  double total_amp = 0.0;
  double bin_width = (double)SAMPLING_FREQ_HZ / SAMPLES;

  for (int i = 1; i < (SAMPLES / 2); i++) {
    double amp = vReal[i];
    double freq = i * bin_width;

    if (amp > fft_max_amp) fft_max_amp = amp;
    weighted_sum += freq * amp;
    total_amp += amp;
  }

  double spectral_centroid = (total_amp > 0.0001) ? (weighted_sum / total_amp) : 0.0;

  Serial.println("[DEBUG] 3. Reading BME280 and VL53L0X...");

  // 3. SENSOR READINGS (SAFE)
  float temp = bme.readTemperature();
  float hum = bme.readHumidity();
  float press = bme.readPressure() / 100.0F;

  // Retrieve distance measurement from laser sensor
  VL53L0X_RangingMeasurementData_t measure;
  lox.rangingTest(&measure, false);

  int distance = (measure.RangeStatus != 4 && 
                  measure.RangeMilliMeter >= 20 && 
                  measure.RangeMilliMeter <= 2000) 
                 ? measure.RangeMilliMeter : -1;

  Serial.println("[DEBUG] 4. Sending MQTT packet...");

  // 4. JSON PREPARATION AND TRANSMISSION
  JsonDocument doc;

  doc["acc_rms"] = acc_rms;
  doc["acc_std"] = acc_std;
  doc["acc_peak"] = acc_peak;
  doc["acc_p2p"] = acc_p2p;
  doc["crest_factor"] = crest_factor;
  doc["skewness"] = skewness;
  doc["kurtosis"] = kurtosis;
  doc["fft_dom_freq"] = fft_dom_freq;
  doc["fft_max_amp"] = fft_max_amp;
  doc["spectral_centroid"] = spectral_centroid;

  doc["temperature"] = temp;
  doc["humidity"] = hum;
  doc["pressure"] = press;
  doc["distance"] = distance;

  char buffer[768];
  serializeJson(doc, buffer);

  // Increase PubSubClient buffer size right before publishing
  client.setBufferSize(1024);

  if (client.publish("factory/machine1/telemetry", buffer)) {
    Serial.println("[ESP32 Edge] Data packet sent successfully!");
  } else {
    Serial.println("[MQTT ERROR] client.publish() returned false (payload too large?)");
  }
}