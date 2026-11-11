from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional
import json
import sqlite3
import io
import os

import numpy as np
import requests
from PIL import Image
from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "smart_agriculture.db"
MODEL_PATH = BASE_DIR / "disease_model.keras"
LABELS_PATH = BASE_DIR / "disease_labels.json"

app = FastAPI(
    title="Smart Agriculture API",
    description="Backend for the Smart Agriculture Android app and future ESP32 devices.",
    version="1.0.0"
)

CROP_PROFILES = {
    "Tomato": {"typical_days_to_maturity": 100, "prototype_moisture_threshold_pct": 40, "water_factor": 0.35,
               "notes": "Duration varies by variety, transplanting date, climate and cultivation method."},
    "Rice": {"typical_days_to_maturity": 120, "prototype_moisture_threshold_pct": 55, "water_factor": 0.25,
             "notes": "Water management differs substantially between flooded and alternate wetting systems."},
    "Wheat": {"typical_days_to_maturity": 120, "prototype_moisture_threshold_pct": 35, "water_factor": 0.35,
              "notes": "Duration varies with cultivar, temperature and planting conditions."},
    "Chilli": {"typical_days_to_maturity": 150, "prototype_moisture_threshold_pct": 38, "water_factor": 0.30,
               "notes": "May have multiple pickings; first harvest and final maturity are different targets."},
    "Groundnut": {"typical_days_to_maturity": 110, "prototype_moisture_threshold_pct": 35, "water_factor": 0.30,
                  "notes": "Duration varies with variety, season and soil conditions."},
    "Maize": {"typical_days_to_maturity": 100, "prototype_moisture_threshold_pct": 35, "water_factor": 0.35,
              "notes": "Duration varies with hybrid, season and harvest purpose."}
}

def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with connect() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS sensor_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, device_id TEXT,
            crop TEXT NOT NULL, soil_moisture REAL NOT NULL, air_temperature REAL,
            humidity REAL, soil_temperature REAL, rainfall_mm REAL, source TEXT DEFAULT 'unknown')""")
        c.execute("""CREATE TABLE IF NOT EXISTS irrigation_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, crop TEXT,
            decision TEXT, water_mm REAL, details TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS disease_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, crop TEXT,
            predicted_class TEXT, confidence REAL, notes TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS device_commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, device_id TEXT,
            command TEXT, status TEXT, details TEXT)""")

init_db()

class SensorReading(BaseModel):
    crop: str = Field(min_length=1, max_length=80)
    soil_moisture: float = Field(ge=0, le=100)
    air_temperature: Optional[float] = Field(default=None, ge=-30, le=80)
    humidity: Optional[float] = Field(default=None, ge=0, le=100)
    soil_temperature: Optional[float] = Field(default=None, ge=-30, le=90)
    rainfall_mm: Optional[float] = Field(default=0, ge=0, le=1000)
    device_id: Optional[str] = Field(default="manual", max_length=100)
    source: str = Field(default="app", max_length=40)

class IrrigationRequest(BaseModel):
    crop: str = "Tomato"
    soil_moisture: float = Field(ge=0, le=100)
    air_temperature: float = Field(default=30, ge=-30, le=80)
    humidity: float = Field(default=60, ge=0, le=100)
    forecast_rain_mm: float = Field(default=0, ge=0, le=1000)
    growth_stage: str = "Vegetative"
    soil_type: str = "Unknown"

class MaturityRequest(BaseModel):
    crop: str = "Tomato"
    sowing_date: date
    growth_stage: str = "Vegetative"
    variety: Optional[str] = None

class DeviceCommand(BaseModel):
    device_id: str = Field(min_length=1, max_length=100)
    command: str = Field(min_length=1, max_length=50)
    duration_seconds: int = Field(default=0, ge=0, le=300)

def weather_for(location: str):
    try:
        g = requests.get("https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 1, "language": "en", "format": "json"}, timeout=8)
        g.raise_for_status()
        results = g.json().get("results", [])
        if not results:
            return {"ok": False, "error": f"Location not found: {location}"}
        place = results[0]
        r = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": place["latitude"], "longitude": place["longitude"],
            "current": "temperature_2m,relative_humidity_2m,precipitation",
            "hourly": "precipitation,temperature_2m,relative_humidity_2m",
            "forecast_days": 2, "timezone": "auto"
        }, timeout=8)
        r.raise_for_status()
        payload = r.json()
        current, hourly = payload.get("current", {}), payload.get("hourly", {})
        times = hourly.get("time", [])
        rain = hourly.get("precipitation", [])
        now = current.get("time", "")
        start = next((i for i, t in enumerate(times) if t >= now), 0)
        next_rain = sum(float(x or 0) for x in rain[start:start+6])
        next_24 = sum(float(x or 0) for x in rain[start:start+24])
        return {"ok": True, "location": place.get("name", location),
            "temperature_c": current.get("temperature_2m"),
            "humidity_pct": current.get("relative_humidity_2m"),
            "current_precipitation_mm": current.get("precipitation"),
            "rain_next_6h_mm": round(next_rain, 2), "rain_next_24h_mm": round(next_24, 2),
            "time": now, "timezone": payload.get("timezone")}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def irrigation_logic(req: IrrigationRequest):
    profile = CROP_PROFILES.get(req.crop, CROP_PROFILES["Tomato"])
    threshold = profile["prototype_moisture_threshold_pct"]
    reasons = [
        f"Soil moisture is {req.soil_moisture:.1f}% against a provisional {threshold}% trigger.",
        f"Forecast rainfall for the next several hours is {req.forecast_rain_mm:.1f} mm.",
        f"Growth stage: {req.growth_stage}; soil type: {req.soil_type}."
    ]
    water_mm = 0.0
    if req.soil_moisture < threshold and req.forecast_rain_mm >= 4:
        decision = "WAIT_AND_RECHECK"
        summary = "Moisture is below the provisional trigger, but forecast rain may contribute water. Recheck soil after rainfall."
        reasons.append("Forecast uncertainty is material; do not assume the rain will occur.")
    elif req.soil_moisture < threshold:
        decision = "IRRIGATION_MAY_BE_NEEDED"
        summary = "Moisture is below the provisional trigger and little near-term rain is forecast. Verify the sensor and field before irrigating."
        water_mm = round(max(0, min(8, (threshold - req.soil_moisture) * profile["water_factor"])), 1)
        reasons.append("Water depth is a rough prototype estimate, not a calibrated irrigation prescription.")
    else:
        decision = "WAIT_AND_MONITOR"
        summary = "The reading is at or above the provisional trigger. Continue monitoring crop stage, root-zone moisture and forecast."
    if req.air_temperature >= 35:
        reasons.append("High temperature may increase demand; inspect the crop for heat or water stress.")
    if req.humidity >= 85:
        reasons.append("High humidity may be relevant to some disease risks but does not establish a disease diagnosis.")
    return {"decision": decision, "summary": summary, "estimated_water_mm": water_mm,
        "confidence": "Prototype rule-based result; not a calibrated ML confidence score",
        "reasons": reasons, "threshold_used_pct": threshold,
        "warning": "Validate thresholds for the actual crop, soil, sensor and local agronomic practice before field use."}

def predict_disease(image_bytes: bytes):
    if not MODEL_PATH.exists() or not LABELS_PATH.exists():
        return {"available": False, "message": "No trained disease model found. Train and evaluate one with train_disease_model.py before diagnosis."}
    try:
        import tensorflow as tf
        model = tf.keras.models.load_model(MODEL_PATH)
        labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB").resize((224, 224))
        arr = np.asarray(img, dtype=np.float32) / 255.0
        probs = model.predict(np.expand_dims(arr, axis=0), verbose=0)[0]
        idx = int(np.argmax(probs))
        confidence = float(probs[idx])
        label = labels[idx] if idx < len(labels) else f"class_{idx}"
        return {"available": True, "predicted_class": label, "confidence": round(confidence, 4),
                "message": "Model output is a screening result, not a confirmed diagnosis.",
                "next_step": "Inspect symptoms and consult local agricultural guidance; do not apply treatment solely from this result."}
    except Exception as e:
        return {"available": False, "message": f"Model inference failed: {e}"}

@app.get("/health")
def health():
    return {"status": "ok", "service": "smart-agriculture-api", "version": "1.0.0"}

@app.get("/api/crops")
def list_crops():
    return CROP_PROFILES

@app.get("/api/weather")
def weather(location: str = "Chennai"):
    return weather_for(location)

@app.post("/api/sensor-readings", status_code=201)
def add_sensor_reading(req: SensorReading):
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    data = req.model_dump()
    with connect() as c:
        c.execute("""INSERT INTO sensor_readings
        (timestamp, device_id, crop, soil_moisture, air_temperature, humidity, soil_temperature, rainfall_mm, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (timestamp, data["device_id"], data["crop"], data["soil_moisture"], data["air_temperature"],
         data["humidity"], data["soil_temperature"], data["rainfall_mm"], data["source"]))
    return {"saved": True, "timestamp": timestamp}

@app.get("/api/sensor-readings")
def get_sensor_readings(limit: int = 100):
    if limit < 1 or limit > 1000:
        raise HTTPException(400, "limit must be between 1 and 1000")
    with connect() as c:
        rows = c.execute("SELECT * FROM sensor_readings ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(x) for x in rows]

@app.post("/api/irrigation/recommend")
def irrigation_recommend(req: IrrigationRequest):
    result = irrigation_logic(req)
    with connect() as c:
        c.execute("INSERT INTO irrigation_events (timestamp, crop, decision, water_mm, details) VALUES (?, ?, ?, ?, ?)",
            (datetime.now().astimezone().isoformat(timespec="seconds"), req.crop, result["decision"],
             result["estimated_water_mm"], json.dumps(result)))
    return result

@app.post("/api/crop/maturity")
def crop_maturity(req: MaturityRequest):
    profile = CROP_PROFILES.get(req.crop, CROP_PROFILES["Tomato"])
    elapsed = max(0, (date.today() - req.sowing_date).days)
    duration = profile["typical_days_to_maturity"]
    remaining = max(0, duration - elapsed)
    return {"crop": req.crop, "variety": req.variety, "growth_stage": req.growth_stage,
        "days_since_sowing": elapsed, "typical_days_to_maturity": duration,
        "estimated_days_remaining": remaining,
        "estimated_maturity_date": (date.today() + timedelta(days=remaining)).isoformat(),
        "message": profile["notes"],
        "warning": "Broad duration estimate, not a validated machine-learning harvest prediction."}

@app.post("/api/disease/analyze")
async def disease_analyze(crop: str = "Unknown", image: UploadFile = File(...)):
    if image.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(415, "Upload a JPG, PNG or WEBP image.")
    raw = await image.read()
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, "Image must be 10 MB or smaller.")
    result = predict_disease(raw)
    if result.get("available") and "predicted_class" in result:
        with connect() as c:
            c.execute("INSERT INTO disease_reports (timestamp, crop, predicted_class, confidence, notes) VALUES (?, ?, ?, ?, ?)",
                (datetime.now().astimezone().isoformat(timespec="seconds"), crop, result["predicted_class"],
                 result["confidence"], result["message"]))
    return result

@app.get("/api/dashboard")
def dashboard(location: str = "Chennai", crop: str = "Tomato"):
    with connect() as c:
        latest = c.execute("SELECT * FROM sensor_readings ORDER BY id DESC LIMIT 1").fetchone()
        events = c.execute("SELECT * FROM irrigation_events ORDER BY id DESC LIMIT 10").fetchall()
    return {"weather": weather_for(location), "crop": crop,
        "latest_sensor_reading": dict(latest) if latest else None,
        "recent_irrigation_events": [dict(x) for x in events]}

@app.get("/api/device/status")
def device_status(device_id: str = "esp32-1"):
    with connect() as c:
        last = c.execute("SELECT * FROM sensor_readings WHERE device_id=? ORDER BY id DESC LIMIT 1", (device_id,)).fetchone()
    return {"device_id": device_id, "last_reading": dict(last) if last else None,
            "pump_control_enabled": False, "message": "Pump actuation is disabled until hardware safety integration is completed."}

@app.post("/api/device/command")
def device_command(req: DeviceCommand):
    # Deliberately fail closed. This endpoint is an integration contract, not a live pump controller.
    with connect() as c:
        c.execute("INSERT INTO device_commands (timestamp, device_id, command, status, details) VALUES (?, ?, ?, ?, ?)",
            (datetime.now().astimezone().isoformat(timespec="seconds"), req.device_id, req.command,
             "REJECTED_SAFE_DEFAULT", "Pump actuation disabled in software starter."))
    raise HTTPException(423, "Device actuation is disabled until authentication, interlocks, timeout and hardware tests are implemented.")
