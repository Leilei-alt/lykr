# Pump Curve Regression

This folder is independent from the original COP project.

The regression step still consumes direct pump samples:

- `pump_id`
- `Q`: pump flow, m3/h
- `H`: pump head, m
- `w`: speed ratio, usually frequency / rated_frequency
- `eta`: pump efficiency, 0-1. If input is percent such as 75, it is converted to 0.75.
- `status`: optional, running rows are kept when status is truthy.

When `Q`, `w`, and `eta` cannot be read directly, use `sample_builder.py` first.
In this project version, `H` is treated as a direct pump head point and is not calculated from pressure difference.
The current web workflow reads separated header-controller, chiller, and pump tables, then joins rows by `sample_time` and `group_id`.

## Build Samples From Raw Points

Raw point input is a wide table. Column names should match the point names in:

```text
F:\lykr\pump_model_config\pump_model_config.template.json
```

The builder supports the two current flow cases:

- chilled water: read group total flow, then allocate it to running pumps
- cooling water: sum running cooling facility flows, then allocate it to running pumps

Calculated fields in the separated-table workflow:

```text
Q_total = sum(flow_value) for the same source type, sample_time, and group_id
discard sample when max(running pump w)-min(running pump w) > 0.002
Q_i = Q_total / running_pump_count
eta = 0.00275 * Q * H / power
```

If only one pump is running in a group:

```text
Q_i = Q_total
```

If multiple similar pumps are running:

```text
Q_i = Q_total * w_i / sum(w_running)
```

In the separated-table workflow, multiple pumps are allocated equally after the speed-ratio consistency check:

```text
Q_i = Q_total / running_pump_count
```

Example:

```powershell
cd F:\lykr\pump_curve_regression
python sample_builder.py build --config F:\lykr\pump_model_config\pump_model_config.template.json --input sample_raw_points.csv --output output\derived_pump_samples.csv --rejects output\derived_pump_samples_rejected.csv
```

Then fit with the derived samples:

```powershell
python pump_curve_regression.py fit --input output\derived_pump_samples.csv --output-dir output
```

## Build Samples From MySQL

Create tables and import variable definitions plus example raw point values.
The JSON config stays in the project folder and is not stored in MySQL:

```powershell
cd F:\lykr\pump_curve_regression
python sample_builder.py seed-db --mysql-exe G:\mysql-8.0.46-winx64\bin\mysql.exe --host 127.0.0.1 --port 3306 --user root --password "wdlwdl123." --database pump_curve_model --config F:\lykr\pump_model_config\pump_model_config.template.json --input sample_raw_points.csv --dataset-name sample_raw_points
```

Or generate demo raw points directly into MySQL. This example creates 50 time points:

```powershell
python sample_builder.py seed-demo-db --mysql-exe G:\mysql-8.0.46-winx64\bin\mysql.exe --host 127.0.0.1 --port 3306 --user root --password "wdlwdl123." --database pump_curve_model --config F:\lykr\pump_model_config\pump_model_config.template.json --dataset-name sample_raw_points --sample-count 50
```

Generate demo data for the separated table structure:

```powershell
python sample_builder.py seed-separated-demo-db --mysql-exe G:\mysql-8.0.46-winx64\bin\mysql.exe --host 127.0.0.1 --port 3306 --user root --password "wdlwdl123." --database pump_curve_model --config F:\lykr\pump_model_config\pump_model_config.template.json --dataset-name sample_raw_points --sample-count 50
```

Build regression samples by reading raw points from MySQL:

```powershell
python sample_builder.py build-db --mysql-exe G:\mysql-8.0.46-winx64\bin\mysql.exe --host 127.0.0.1 --port 3306 --user root --password "wdlwdl123." --database pump_curve_model --config F:\lykr\pump_model_config\pump_model_config.template.json --dataset-name sample_raw_points --output output\derived_pump_samples_from_db.csv --rejects output\derived_pump_samples_from_db_rejected.csv
```

Fit and draw curves from the database-derived samples:

```powershell
python pump_curve_regression.py fit --input output\derived_pump_samples_from_db.csv --output-dir output\db_fit
```

## Models

Head curve:

```text
Q_eq = Q / w
H_eq = H / w^2
H_eq = a * Q_eq^2 + b * Q_eq + c
H = a * Q^2 + b * w * Q + c * w^2
```

Efficiency curve:

```text
Q_eq = Q / w
eta = j * Q_eq^2 + k * Q_eq + l
eta = j * (Q / w)^2 + k * (Q / w) + l
```

## Run sample fit

```powershell
cd F:\lykr\pump_curve_regression
python pump_curve_regression.py fit --input sample_direct_pump_data.csv --output-dir output
```

Outputs:

- `output/pump_curve_fit_results.json`
- `output/pump_curve_fitted_samples.csv`
- `output/*_head_curve.png`
- `output/*_efficiency_curve.png`
- `output/*_head_normalized_curve.png`
- `output/*_efficiency_normalized_curve.png`

## Create MySQL tables

The DDL is in `db_schema.mysql.sql`.

Example:

```powershell
mysql --host=127.0.0.1 --port=3306 --user=root --password=123456 < db_schema.mysql.sql
```

Or through the Python helper:

```powershell
python pump_curve_regression.py init-db --mysql-exe G:\mysql-8.0.46-winx64\bin\mysql.exe --host 127.0.0.1 --port 3306 --user root --password 123456 --database pump_curve_model
```
