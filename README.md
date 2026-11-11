# Smart Agriculture — Android App + AI Backend

This package is an app-first software project:
- Flutter Android application source (`mobile_app/`)
- FastAPI backend (`backend/`)
- SQLite storage by default
- Weather forecast integration via Open-Meteo
- Weather-aware irrigation recommendations and explainable factors
- Crop maturity estimate
- Plant-image diagnosis API integration
- Disease-model training pipeline (`backend/train_disease_model.py`)
- ESP32 sensor ingestion API and safe command/status interfaces for later hardware integration
- Pest monitoring extension interface

## Important truth about model readiness
The app and backend are runnable, but crop-specific thresholds and harvest durations are starter profiles that must be validated for the target crop/region. Disease inference becomes active after you train a model with a suitable labeled dataset and save its model file. No model can be honestly described as accurate before evaluation on held-out images. Pump actuation is deliberately not enabled until hardware safety logic is integrated and tested.

## 1. Backend setup (Windows / VS Code)
Install Python 3.11 or 3.12 recommended.

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

API docs: `http://127.0.0.1:8000/docs`

Weather forecast needs internet access. If testing the Android emulator, backend URL is `http://10.0.2.2:8000`. For a physical Android phone, use your computer's LAN IP address, e.g. `http://192.168.1.10:8000`, and ensure both devices are on the same network. Do not expose this development server directly to the public internet.

## 2. Flutter app setup
Install Flutter SDK and Android Studio / Android SDK. In `mobile_app/` run:

```powershell
flutter create . --platforms android
flutter pub get
flutter run
```

If `flutter create .` asks to overwrite files, do not overwrite `lib/main.dart`; generate the platform folder only or create a fresh Flutter app and copy `lib/main.dart` and `pubspec.yaml` into it.

Set the backend address in `mobile_app/lib/main.dart`:
- Android emulator: `http://10.0.2.2:8000`
- Physical phone: `http://YOUR_COMPUTER_LAN_IP:8000`

For local HTTP testing, Android may require cleartext HTTP to be allowed in `android/app/src/main/AndroidManifest.xml` by adding `android:usesCleartextTraffic="true"` to the `<application ...>` element. Use HTTPS for production.

## 3. Disease classifier training
Use a labeled image dataset with one folder per class, for example:
```
dataset/
  Tomato___healthy/
  Tomato___Early_blight/
  Tomato___Late_blight/
```
Then run:
```powershell
cd backend
pip install -r requirements-ml.txt
python train_disease_model.py --data-dir "C:\path\to\dataset" --output disease_model.keras --epochs 8
```
The script creates a training/validation split and writes class labels alongside the model. Check the reported validation metrics and evaluate on independent field images before relying on it. A dataset with multiple crops should be selected only if you intend to support those crops.

## 4. API overview
- `GET /health`
- `GET /api/weather?location=Chennai`
- `POST /api/sensor-readings`
- `GET /api/sensor-readings`
- `POST /api/irrigation/recommend`
- `POST /api/crop/maturity`
- `POST /api/disease/analyze` (multipart image upload)
- `GET /api/dashboard?location=Chennai&crop=Tomato`
- `GET /api/device/status`
- `POST /api/device/command` (safe placeholder; pump commands are rejected by default)

## 5. Hardware integration later
ESP32 can POST JSON sensor readings to `/api/sensor-readings`. Include a unique `device_id`. Pump/valve control remains disabled by default. Before enabling it, add device authentication, command expiry, interlocks, max-run timer, dry-run protection, manual override and field testing.

## 6. Scope
This is a complete software source foundation, not a claim of field-validated agronomic performance. In particular:
- Irrigation advice is a transparent baseline until calibrated against soil, crop, sensor and field measurements.
- Maturity is an estimate using crop profiles; robust ML maturity prediction needs dated crop observations and actual harvest labels.
- Disease detection requires a trained model and validation. If no model exists, the API says so rather than fabricating a disease result.
- Acoustic pest deterrence is not assumed effective. The package includes an extension point for future pest monitoring/experimentation.
