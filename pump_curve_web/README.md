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
  -> MySQL separated device tables by sample_time
  -> local JSON config
  -> sum flow by source type, sample_time, and group_id
  -> match running pumps in the same group
  -> discard group/time samples when max(w)-min(w) > 0.02
  -> allocate Q_total equally to running pumps
  -> derive Q/H/w/eta
  -> chart data returned to Vue and drawn by ECharts
```

The config file stays in:

```text
F:\lykr\pump_model_config\pump_model_config.template.json
```

MySQL stores the new separated source data in:

```text
pump_header_controller_values: header controller flow point 0x0000024C
pump_chiller_values: chiller flow point 0x0000021E
pump_device_values: pump status, speed_ratio, head, power_kw
```

Seed demo data for the new table structure:

```powershell
cd F:\lykr\pump_curve_regression
python sample_builder.py seed-separated-demo-db --mysql-exe G:\mysql-8.0.46-winx64\bin\mysql.exe --host 127.0.0.1 --port 3306 --user root --password "wdlwdl123." --database pump_curve_model --config F:\lykr\pump_model_config\pump_model_config.template.json --dataset-name sample_raw_points --sample-count 50
```
