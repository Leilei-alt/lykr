# Pump Curve Web

FastAPI + Vue/Vite web app for pump H-Q and eta-Q regression.

## Backend

```powershell
cd F:\lykr\pump_curve_web\backend
python -m uvicorn main:app --host 127.0.0.1 --port 8010 --reload
```

## Frontend

```powershell
cd F:\lykr\pump_curve_web\frontend
npm.cmd install
npm.cmd run dev
```

Open:

```text
http://127.0.0.1:5174
```

## Data Flow

```text
Vue page selections
  -> FastAPI /api/regression
  -> MySQL pump_raw_point_values by sample_time
  -> local JSON config
  -> derive Q/H/w/eta
  -> regression plots
  -> image URLs returned to Vue
```

The config file stays in:

```text
F:\lykr\pump_model_config\pump_model_config.template.json
```

MySQL stores raw point values with time in:

```text
pump_raw_point_values.sample_time
```
