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
Vue time range + theory coefficients (H-Q a/b/c, eta-Q j/k/l)
  -> FastAPI /api/regression
  -> MySQL ly_czwxc.ly_cpn reads device catalog, names, types, and group_id
  -> InfluxDB czwxc_1 reads time-series values by true_cpn_name and point measurement
  -> local JSON config
  -> calculate every group and every running pump in the selected time range
  -> sum flow by source type, sample_time, and group_id
  -> match running pumps in the same group
  -> discard group/time samples when max(w)-min(w) > 0.002
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

MySQL now stores the device catalog in:

```text
database: ly_czwxc
table: ly_cpn
cpn_type: 32 = chiller, 36 = pump, 38 = header controller
group_id: group number used to pair source devices with pumps
show_name: frontend display name
true_cpn_name: InfluxDB cpn_name tag value
```

InfluxDB now stores the time-series values in:

```text
bucket/database: czwxc_1
measurement format: ly_{cpn_type_hex}_FFFFFFFF_{point_code} (cpn_type 32/36/38 -> 20/24/26 hex, point_code without 0x prefix)
tag filter: cpn_name = ly_cpn.true_cpn_name
field filter: _field = value
```

Point mapping:

```text
ly_20_FFFFFFFF_00000200: chiller status
ly_20_FFFFFFFF_0000021D: chiller flow
ly_24_FFFFFFFF_00000200: pump status
ly_24_FFFFFFFF_00000201: pump speed ratio w
ly_24_FFFFFFFF_00000212: pump head H
ly_24_FFFFFFFF_00000220: pump power P
ly_26_FFFFFFFF_0000024A: header controller flow
```

Runtime connection defaults can be overridden with environment variables:

```text
PUMP_CPN_MYSQL_EXE
PUMP_CPN_MYSQL_HOST
PUMP_CPN_MYSQL_PORT
PUMP_CPN_MYSQL_USER
PUMP_CPN_MYSQL_PASSWORD
PUMP_CPN_MYSQL_DATABASE
PUMP_CPN_MYSQL_TABLE
PUMP_INFLUX_URL
PUMP_INFLUX_TOKEN
PUMP_INFLUX_ORG
PUMP_INFLUX_BUCKET
PUMP_INFLUX_AGGREGATE_WINDOW
PUMP_INFLUX_TIMEZONE
PUMP_INFLUX_TYPE_CODE_FORMAT
PUMP_INFLUX_POINT_INCLUDE_0X
PUMP_INFLUX_API_VERSION
```

### InfluxDB v2 / v3 switch

The backend reads time-series values through the InfluxDB v3 SQL API
(`POST /api/v3/query_sql`) by default. When the target InfluxDB is v2,
set `"api_version": "v2"` in the `influx` section of `pump_app_config.json`
(or the `PUMP_INFLUX_API_VERSION` environment variable). In v2 mode the
backend queries `POST /api/v2/query` with Flux and parses the CSV response
using the same `org`, `bucket`, measurement, and `cpn_name` settings.

The `aggregate_window` setting is applied by the backend after either the v2
or v3 query. Timestamps are converted to the configured timezone, assigned to
natural windows (for example, `5m`), and the last value for each device and
measurement in each window is retained. This allows independently collected
status, speed, head, power, and flow points to be joined without requiring
their raw timestamps to match to the exact second.

The old demo seed commands below are kept only for local simulated-data tests:

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
