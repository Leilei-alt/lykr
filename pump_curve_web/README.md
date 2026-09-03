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
Vue time range
  -> FastAPI /api/regression
  -> MySQL pump_point_index maps point names to target table columns
  -> MySQL separated device tables by sample_time
  -> local JSON config
  -> calculate every group and every running pump in the selected time range
  -> sum flow by source type, sample_time, and group_id
  -> match running pumps in the same group
  -> discard group/time samples when max(w)-min(w) > 0.02
  -> allocate Q_total equally to running pumps
  -> derive Q/H/w/eta and fit pumps with at least 10 valid samples
  -> return grouped fit results to Vue
  -> Vue switches displayed charts by group dropdown and pump dropdown
```

The frontend supports one or two time ranges. When the second range is filled
with both start and end time, Vue calls `/api/regression` again and renders an
additional set of charts for the same selected group and pump.

The config file stays in:

```text
F:\lykr\pump_model_config\pump_model_config.template.json
```

MySQL stores the new separated source data in:

```text
pump_header_controller_values: header controller status point 0x00000200, header controller flow point 0x0000024A
pump_chiller_values: chiller status and flow values; point names are resolved by pump_point_index
pump_device_values: pump status, speed_ratio, head, power_kw; point names are resolved by pump_point_index
pump_point_index: point_name to target table/column mapping
```

Pump point index:

```text
0x00000200 -> pump_device_values.status
0x00000210 -> pump_device_values.speed_ratio
0x00000212 -> pump_device_values.head
0x00000220 -> pump_device_values.power_kw
0x00000200 -> pump_chiller_values.status
0x0000021D -> pump_chiller_values.flow_value
0x00000200 -> pump_header_controller_values.status
0x0000024A -> pump_header_controller_values.flow_value
```

Seed demo data for the new table structure:

```powershell
cd F:\lykr\pump_curve_regression
python sample_builder.py seed-separated-demo-db --mysql-exe G:\mysql-8.0.46-winx64\bin\mysql.exe --host 127.0.0.1 --port 3306 --user root --password "wdlwdl123." --database pump_curve_model --config F:\lykr\pump_model_config\pump_model_config.template.json --dataset-name sample_raw_points --sample-count 50
```

Append dispersed demo time ranges for two-range comparison tests:

```powershell
cd F:\lykr\pump_curve_regression
python seed_extra_time_ranges.py --dataset-name sample_raw_points
python seed_theory_curves.py --dataset-name sample_raw_points
```

The demo seed creates:

```text
header_group_1: HCC1, HCC2 + CHWP1, CHWP2
header_group_2: HCC3, HCC4 + CHWP3, CHWP4
header_group_3: HCC5, HCC6 + CHWP5, CHWP6

chiller_group_1: CH1, CH2, CH3 + CWP1, CWP2
chiller_group_2: CH4, CH5, CH6 + CWP3, CWP4
chiller_group_3: CH7, CH8, CH9 + CWP5, CWP6
```

Demo status values include both 0 and 1 for chillers, pumps, and header
controllers. The generated patterns keep at least one source device and one
pump running in each group/time sample for ordinary regression tests.
