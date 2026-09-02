# Pump Curve Regression

This folder is independent from the original COP project.

This first implementation assumes each pump already has direct sample data:

- `pump_id`
- `Q`: pump flow, m3/h
- `H`: pump head, m
- `w`: speed ratio, usually frequency / rated_frequency
- `eta`: pump efficiency, 0-1. If input is percent such as 75, it is converted to 0.75.
- `status`: optional, running rows are kept when status is truthy.

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