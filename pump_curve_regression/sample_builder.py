#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Build direct pump regression samples from raw point data.

The regression module expects:
  timestamp, pump_id, group_id, side, status, Q, H, w, eta

This builder derives those fields from the pump model JSON config:
  - H is read directly from each pump's configured head point.
  - w = frequency / rated_frequency.
  - Q is allocated from group total flow.
  - eta = 0.002725 * Q * H / power, where Q is m3/h, H is m, power is kW.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


DEFAULT_EFFICIENCY_FACTOR = 9.81 / 3600.0


@dataclass
class BuildIssue:
    timestamp: Optional[str]
    group_id: Optional[str]
    pump_id: Optional[str]
    reason: str


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".csv", ".txt"}:
        return pd.read_csv(path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if suffix == ".json":
        return pd.read_json(path)
    raise ValueError(f"Unsupported input file type: {path.suffix}")


def read_config(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sql_quote(value: Any) -> str:
    if value is None:
        return "NULL"
    text = str(value)
    return "'" + text.replace("\\", "\\\\").replace("'", "''") + "'"


def sql_number_or_text(value: Any) -> Tuple[str, str]:
    numeric = to_float(value)
    if numeric is None:
        return "NULL", sql_quote(value)
    return repr(float(numeric)), sql_quote(value)


def mysql_cmd(mysql_exe: Path, host: str, port: int, user: str, password: str, database: Optional[str] = None) -> List[str]:
    cmd = [
        str(mysql_exe),
        f"--host={host}",
        f"--port={port}",
        f"--user={user}",
        f"--password={password}",
        "--default-character-set=utf8mb4",
        "--batch",
        "--raw",
    ]
    if database:
        cmd.append(f"--database={database}")
    return cmd


def run_mysql(
    mysql_exe: Path,
    host: str,
    port: int,
    user: str,
    password: str,
    sql: str,
    database: Optional[str] = None,
) -> str:
    proc = subprocess.run(
        mysql_cmd(mysql_exe, host, port, user, password, database),
        input=sql,
        text=True,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout


def detect_timestamp_column(df: pd.DataFrame, configured: Optional[str] = None) -> Optional[str]:
    if configured and configured in df.columns:
        return configured
    for candidate in ["timestamp", "time", "datetime", "date_time", "sample_time"]:
        if candidate in df.columns:
            return candidate
    lower_map = {str(col).lower(): col for col in df.columns}
    for candidate in ["timestamp", "time", "datetime", "date_time", "sample_time"]:
        if candidate in lower_map:
            return lower_map[candidate]
    return None


def is_truthy(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value) > 0
    normalized = str(value).strip().lower()
    return normalized in {"1", "true", "yes", "y", "on", "run", "running", "open"}


def to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def point_value(row: pd.Series, point_name: Optional[str]) -> Any:
    if not point_name:
        return None
    if point_name in row.index:
        return row[point_name]
    return None


def point_float(row: pd.Series, point_name: Optional[str]) -> Optional[float]:
    return to_float(point_value(row, point_name))


def point_running(row: pd.Series, point_name: Optional[str]) -> bool:
    return is_truthy(point_value(row, point_name))


def valid_filters(config: Dict[str, Any]) -> Dict[str, float]:
    defaults = config.get("defaults", {})
    return defaults.get("valid_filters", {})


def passes_filters(sample: Dict[str, Any], filters: Dict[str, float]) -> Tuple[bool, Optional[str]]:
    checks = [
        ("Q", "min_flow", None),
        ("H", "min_head", None),
        ("power", "min_power", None),
        ("w", "min_speed_ratio", "max_speed_ratio"),
        ("eta", "min_efficiency", "max_efficiency"),
    ]
    for field, min_key, max_key in checks:
        value = to_float(sample.get(field))
        if value is None:
            return False, f"{field} is missing or non-numeric"
        if min_key in filters and value <= float(filters[min_key]):
            return False, f"{field} <= {filters[min_key]}"
        if max_key and max_key in filters and value > float(filters[max_key]):
            return False, f"{field} > {filters[max_key]}"
    return True, None


def get_group_total_flow(group: Dict[str, Any], row: pd.Series) -> Tuple[Optional[float], int, str]:
    flow_source = group.get("flow_source", {})
    method = flow_source.get("method")

    if method == "group_total_meter":
        point = flow_source.get("total_flow")
        return point_float(row, point), 0, str(point)

    if method == "sum_facility_flow":
        only_running = bool(flow_source.get("only_running_facilities", True))
        total = 0.0
        count = 0
        source_points = []

        facilities = group.get("facilities", [])
        facilities_with_flow = [facility for facility in facilities if facility.get("flow")]
        if facilities_with_flow:
            for facility in facilities_with_flow:
                running = True
                if only_running and facility.get("status"):
                    running = point_running(row, facility.get("status"))
                if not running:
                    continue
                flow = point_float(row, facility.get("flow"))
                if flow is None:
                    continue
                total += flow
                count += 1
                source_points.append(facility.get("flow"))
        else:
            for point in flow_source.get("flow_points", []):
                flow = point_float(row, point)
                if flow is None:
                    continue
                total += flow
                count += 1
                source_points.append(point)

        return total, count, "+".join(source_points)

    return None, 0, f"unsupported flow_source method: {method}"


def running_pump_infos(
    group: Dict[str, Any],
    row: pd.Series,
    default_rated_frequency: float,
) -> List[Dict[str, Any]]:
    infos: List[Dict[str, Any]] = []
    for pump in group.get("pumps", []):
        if not point_running(row, pump.get("status")):
            continue

        frequency = point_float(row, pump.get("frequency"))
        rated_frequency = to_float(pump.get("rated_frequency_hz")) or default_rated_frequency
        head = point_float(row, pump.get("head"))
        power = point_float(row, pump.get("power"))
        rated_flow = to_float(pump.get("rated_flow_m3h"))

        speed_ratio = None
        if frequency is not None and rated_frequency and rated_frequency > 0:
            speed_ratio = frequency / rated_frequency

        infos.append(
            {
                "pump": pump,
                "pump_id": pump.get("id"),
                "frequency": frequency,
                "rated_frequency": rated_frequency,
                "rated_flow": rated_flow,
                "H": head,
                "power": power,
                "w": speed_ratio,
            }
        )
    return infos


def allocation_weight(method: str, info: Dict[str, Any]) -> Optional[float]:
    if method == "equal":
        return 1.0
    if method == "by_speed_ratio":
        return to_float(info.get("w"))
    if method == "by_rated_flow_speed":
        rated_flow = to_float(info.get("rated_flow"))
        speed_ratio = to_float(info.get("w"))
        if rated_flow is None or speed_ratio is None:
            return None
        return rated_flow * speed_ratio
    return None


def allocate_flows(q_total: float, pump_infos: List[Dict[str, Any]], allocation: Dict[str, Any]) -> Tuple[Dict[str, float], str]:
    if len(pump_infos) == 1:
        return {str(pump_infos[0]["pump_id"]): q_total}, "single_running_pump"

    method = allocation.get("method", "by_speed_ratio")
    weights = [allocation_weight(method, info) for info in pump_infos]
    if any(weight is None or weight <= 0 for weight in weights):
        method = allocation.get("fallback_method", "equal")
        weights = [allocation_weight(method, info) for info in pump_infos]

    if any(weight is None or weight <= 0 for weight in weights):
        method = "equal"
        weights = [1.0 for _ in pump_infos]

    total_weight = float(sum(weights))
    return {
        str(info["pump_id"]): q_total * float(weight) / total_weight
        for info, weight in zip(pump_infos, weights)
    }, method


def build_samples(config: Dict[str, Any], raw: pd.DataFrame, timestamp_column: Optional[str] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    defaults = config.get("defaults", {})
    default_rated_frequency = float(defaults.get("rated_frequency_hz", 50))
    efficiency_factor = float(defaults.get("efficiency_factor", DEFAULT_EFFICIENCY_FACTOR))
    filters = valid_filters(config)
    ts_col = detect_timestamp_column(raw, timestamp_column or defaults.get("timestamp_column"))

    samples: List[Dict[str, Any]] = []
    issues: List[BuildIssue] = []

    for row_index, row in raw.iterrows():
        timestamp_value = row[ts_col] if ts_col else row_index
        timestamp = str(timestamp_value) if timestamp_value is not None else None

        for group in config.get("pump_groups", []):
            group_id = group.get("id")
            side = group.get("side", "unknown")
            q_total, facility_running_count, q_source = get_group_total_flow(group, row)
            if q_total is None or q_total <= 0:
                issues.append(BuildIssue(timestamp, group_id, None, "Q_total is missing or <= 0"))
                continue

            pump_infos = running_pump_infos(group, row, default_rated_frequency)
            if not pump_infos:
                issues.append(BuildIssue(timestamp, group_id, None, "no running pump"))
                continue

            q_map, allocation_method = allocate_flows(q_total, pump_infos, group.get("allocation", {}))

            for info in pump_infos:
                pump = info["pump"]
                pump_id = str(info["pump_id"])
                q = q_map[pump_id]
                h = info.get("H")
                power = info.get("power")
                w = info.get("w")
                frequency = info.get("frequency")

                eta = None
                if q is not None and h is not None and power is not None and power > 0:
                    eta = efficiency_factor * q * h / power

                sample = {
                    "timestamp": timestamp,
                    "group_id": group_id,
                    "side": side,
                    "pump_id": pump_id,
                    "status": 1,
                    "pump_status": 1,
                    "facility_running_count": facility_running_count,
                    "pump_running_count": len(pump_infos),
                    "Q_total": q_total,
                    "Q": q,
                    "H": h,
                    "power": power,
                    "frequency": frequency,
                    "rated_frequency": info.get("rated_frequency"),
                    "w": w,
                    "eta": eta,
                    "Q_source": q_source,
                    "H_source": pump.get("head"),
                    "w_source": pump.get("frequency"),
                    "eta_source": "eta = 0.002725 * Q * H / power",
                    "allocation_method": allocation_method,
                }

                ok, reason = passes_filters(sample, filters)
                if ok:
                    sample["quality_flag"] = "valid"
                    samples.append(sample)
                else:
                    issues.append(BuildIssue(timestamp, group_id, pump_id, reason or "invalid sample"))

    return pd.DataFrame(samples), pd.DataFrame([asdict(issue) for issue in issues])


def generate_demo_raw_points(sample_count: int = 50) -> pd.DataFrame:
    """Generate realistic demo raw points for database-based regression tests."""
    from datetime import datetime, timedelta

    start = datetime(2026, 8, 1, 0, 0, 0)
    rows: List[Dict[str, Any]] = []
    denominator = max(sample_count - 1, 1)

    for i in range(sample_count):
        phase = i / denominator
        timestamp = start + timedelta(minutes=5 * i)

        chwp2_on = 1
        cwp2_on = 1
        ch1_on = 1
        ch2_on = 1 if i >= sample_count // 3 else 0
        ch3_on = 1 if i >= sample_count * 2 // 3 else 0

        chwp1_frequency = 36 + 18 * phase + 0.45 * math.sin(i * 0.45)
        chwp2_frequency = 0 if not chwp2_on else 35 + 17 * phase + 0.35 * math.cos(i * 0.36)
        cwp1_frequency = 37 + 17 * phase + 0.40 * math.sin(i * 0.38)
        cwp2_frequency = 0 if not cwp2_on else 36 + 16 * phase + 0.32 * math.cos(i * 0.34)

        rows.append(
            {
                "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "CHW.total_flow": round(220 + 430 * phase + 18 * math.sin(i * 0.28), 3),
                "B101-CH.status": ch1_on,
                "B102-CH.status": ch2_on,
                "B103-CH.status": ch3_on,
                "B101-CH.cw_flow": round(255 + 165 * phase + 12 * math.sin(i * 0.33), 3),
                "B102-CH.cw_flow": 0 if not ch2_on else round(145 + 95 * phase + 8 * math.cos(i * 0.27), 3),
                "B103-CH.cw_flow": 0 if not ch3_on else round(95 + 75 * phase + 6 * math.sin(i * 0.31), 3),
                "CHWP1.status": 1,
                "CHWP1.frequency": round(chwp1_frequency, 3),
                "CHWP1.power": round(34 + 44 * phase + 1.2 * math.sin(i * 0.19), 3),
                "CHWP1.head": round(31 + 16 * phase + 0.9 * math.sin(i * 0.21), 3),
                "CHWP2.status": chwp2_on,
                "CHWP2.frequency": round(chwp2_frequency, 3),
                "CHWP2.power": round(33 + 42 * phase + 1.1 * math.cos(i * 0.22), 3),
                "CHWP2.head": round(30.5 + 15 * phase + 0.8 * math.cos(i * 0.23), 3),
                "CWP1.status": 1,
                "CWP1.frequency": round(cwp1_frequency, 3),
                "CWP1.power": round(34 + 42 * phase + 1.0 * math.sin(i * 0.18), 3),
                "CWP1.head": round(25 + 13 * phase + 0.7 * math.sin(i * 0.25), 3),
                "CWP2.status": cwp2_on,
                "CWP2.frequency": round(cwp2_frequency, 3),
                "CWP2.power": round(33 + 40 * phase + 1.0 * math.cos(i * 0.2), 3),
                "CWP2.head": round(24.5 + 12 * phase + 0.6 * math.cos(i * 0.24), 3),
            }
        )

    return pd.DataFrame(rows)


def variable_unit(role: str, config: Dict[str, Any]) -> Optional[str]:
    defaults = config.get("defaults", {})
    if role in {"group_total_flow", "facility_flow"}:
        return defaults.get("flow_unit", "m3/h")
    if role == "pump_head":
        return defaults.get("head_unit", "m")
    if role == "pump_power":
        return defaults.get("power_unit", "kW")
    if role == "pump_frequency":
        return "Hz"
    if role.endswith("_status"):
        return "bool"
    return None


def add_variable(
    variables: Dict[Tuple[str, str, Optional[str], Optional[str]], Dict[str, Any]],
    config: Dict[str, Any],
    point_name: Optional[str],
    role: str,
    group_id: Optional[str],
    side: Optional[str],
    device_id: Optional[str],
    device_type: str,
    description: str,
) -> None:
    if not point_name:
        return
    key = (point_name, role, group_id, device_id)
    variables[key] = {
        "point_name": point_name,
        "role": role,
        "group_id": group_id,
        "side": side or "unknown",
        "device_id": device_id,
        "device_type": device_type,
        "unit": variable_unit(role, config),
        "description": description,
    }


def collect_variables(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    variables: Dict[Tuple[str, str, Optional[str], Optional[str]], Dict[str, Any]] = {}
    for group in config.get("pump_groups", []):
        group_id = group.get("id")
        side = group.get("side", "unknown")
        flow_source = group.get("flow_source", {})

        if flow_source.get("method") == "group_total_meter":
            add_variable(
                variables,
                config,
                flow_source.get("total_flow"),
                "group_total_flow",
                group_id,
                side,
                group_id,
                "group",
                "Group total flow used to allocate pump flow.",
            )

        for facility in group.get("facilities", []):
            add_variable(
                variables,
                config,
                facility.get("status"),
                "facility_status",
                group_id,
                side,
                facility.get("id"),
                "facility",
                "Facility running status.",
            )
            add_variable(
                variables,
                config,
                facility.get("flow"),
                "facility_flow",
                group_id,
                side,
                facility.get("id"),
                "facility",
                "Cooling facility flow used to calculate cooling-side total flow.",
            )

        for point in flow_source.get("flow_points", []):
            add_variable(
                variables,
                config,
                point,
                "facility_flow",
                group_id,
                side,
                None,
                "facility",
                "Cooling facility flow used to calculate cooling-side total flow.",
            )

        for pump in group.get("pumps", []):
            pump_id = pump.get("id")
            add_variable(variables, config, pump.get("status"), "pump_status", group_id, side, pump_id, "pump", "Pump running status.")
            add_variable(variables, config, pump.get("frequency"), "pump_frequency", group_id, side, pump_id, "pump", "Pump frequency used to calculate speed ratio w.")
            add_variable(variables, config, pump.get("power"), "pump_power", group_id, side, pump_id, "pump", "Pump input power used to calculate eta.")
            add_variable(variables, config, pump.get("head"), "pump_head", group_id, side, pump_id, "pump", "Pump head H, read directly from this point.")

    return sorted(variables.values(), key=lambda item: (item["group_id"] or "", item["device_id"] or "", item["role"], item["point_name"]))


def ensure_schema(mysql_exe: Path, host: str, port: int, user: str, password: str, schema_path: Path) -> None:
    run_mysql(mysql_exe, host, port, user, password, schema_path.read_text(encoding="utf-8"))


def seed_variables(
    mysql_exe: Path,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    variables: List[Dict[str, Any]],
) -> None:
    statements = ["DELETE FROM pump_model_variables;"]
    if variables:
        values = []
        for variable in variables:
            values.append(
                "("
                f"{sql_quote(variable['point_name'])}, "
                f"{sql_quote(variable['role'])}, "
                f"{sql_quote(variable.get('group_id'))}, "
                f"{sql_quote(variable.get('side') or 'unknown')}, "
                f"{sql_quote(variable.get('device_id'))}, "
                f"{sql_quote(variable.get('device_type') or 'unknown')}, "
                f"{sql_quote(variable.get('unit'))}, "
                f"{sql_quote(variable.get('description'))}"
                ")"
            )
        statements.append(
            """
INSERT INTO pump_model_variables
  (point_name, role, group_id, side, device_id, device_type, unit, description)
VALUES
"""
            + ",\n".join(values)
            + ";"
        )
    run_mysql(mysql_exe, host, port, user, password, "\n".join(statements), database)


def seed_raw_values(
    mysql_exe: Path,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    dataset_name: str,
    raw: pd.DataFrame,
    timestamp_column: Optional[str] = None,
) -> int:
    ts_col = detect_timestamp_column(raw, timestamp_column)
    if not ts_col:
        raise ValueError("Raw data must contain a timestamp/time/datetime column when seeding database.")

    statements = [f"DELETE FROM pump_raw_point_values WHERE dataset_name = {sql_quote(dataset_name)};"]
    rows = []
    for _, row in raw.iterrows():
        sample_time = pd.to_datetime(row[ts_col], errors="coerce")
        if pd.isna(sample_time):
            continue
        sample_time_text = sample_time.strftime("%Y-%m-%d %H:%M:%S")
        for column in raw.columns:
            if column == ts_col:
                continue
            value = row[column]
            if value is None or (isinstance(value, float) and math.isnan(value)):
                continue
            numeric_sql, text_sql = sql_number_or_text(value)
            rows.append(
                "("
                f"{sql_quote(dataset_name)}, "
                f"{sql_quote(sample_time_text)}, "
                f"{sql_quote(column)}, "
                f"{numeric_sql}, "
                f"{text_sql}"
                ")"
            )

    for start in range(0, len(rows), 500):
        batch = rows[start : start + 500]
        statements.append(
            """
INSERT INTO pump_raw_point_values
  (dataset_name, sample_time, point_name, numeric_value, text_value)
VALUES
"""
            + ",\n".join(batch)
            + """
ON DUPLICATE KEY UPDATE
  numeric_value = VALUES(numeric_value),
  text_value = VALUES(text_value);
"""
        )

    run_mysql(mysql_exe, host, port, user, password, "\n".join(statements), database)
    return len(rows)


def seed_database(
    mysql_exe: Path,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    schema_path: Path,
    config_path: Path,
    dataset_name: str,
    input_path: Path,
) -> Dict[str, Any]:
    config = read_config(config_path)
    raw = read_table(input_path)
    ensure_schema(mysql_exe, host, port, user, password, schema_path)
    variables = collect_variables(config)
    seed_variables(mysql_exe, host, port, user, password, database, variables)
    value_count = seed_raw_values(mysql_exe, host, port, user, password, database, dataset_name, raw)
    return {
        "database": database,
        "config_file": str(config_path),
        "variable_count": len(variables),
        "dataset_name": dataset_name,
        "raw_row_count": int(len(raw)),
        "raw_value_count": value_count,
    }


def seed_demo_database(
    mysql_exe: Path,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    schema_path: Path,
    config_path: Path,
    dataset_name: str,
    sample_count: int,
) -> Dict[str, Any]:
    config = read_config(config_path)
    raw = generate_demo_raw_points(sample_count)
    ensure_schema(mysql_exe, host, port, user, password, schema_path)
    variables = collect_variables(config)
    seed_variables(mysql_exe, host, port, user, password, database, variables)
    value_count = seed_raw_values(mysql_exe, host, port, user, password, database, dataset_name, raw)
    return {
        "database": database,
        "config_file": str(config_path),
        "variable_count": len(variables),
        "dataset_name": dataset_name,
        "raw_row_count": int(len(raw)),
        "raw_value_count": value_count,
    }


def read_raw_points_from_db(
    mysql_exe: Path,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    dataset_name: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> pd.DataFrame:
    conditions = [f"dataset_name = {sql_quote(dataset_name)}"]
    if start_time:
        conditions.append(f"sample_time >= {sql_quote(start_time)}")
    if end_time:
        conditions.append(f"sample_time <= {sql_quote(end_time)}")
    sql = f"""
SELECT sample_time, point_name, numeric_value, text_value
FROM pump_raw_point_values
WHERE {" AND ".join(conditions)}
ORDER BY sample_time, point_name;
"""
    output = run_mysql(mysql_exe, host, port, user, password, sql, database)
    records: Dict[str, Dict[str, Any]] = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 4 or parts[0] == "sample_time":
            continue
        sample_time, point_name, numeric_value, text_value = parts
        records.setdefault(sample_time, {"timestamp": sample_time})
        records[sample_time][point_name] = None if numeric_value == "NULL" else float(numeric_value)
        if numeric_value == "NULL" and text_value != "NULL":
            records[sample_time][point_name] = text_value

    if not records:
        raise ValueError(f"No raw point values found for dataset: {dataset_name}")
    return pd.DataFrame([records[key] for key in sorted(records.keys())])


def build_from_database(
    mysql_exe: Path,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    config_path: Path,
    dataset_name: str,
    output_path: Path,
    rejects_path: Optional[Path] = None,
) -> Dict[str, Any]:
    config = read_config(config_path)
    raw = read_raw_points_from_db(mysql_exe, host, port, user, password, database, dataset_name)
    samples, rejects = build_samples(config, raw)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    samples.to_csv(output_path, index=False, encoding="utf-8-sig")

    if rejects_path:
        rejects_path.parent.mkdir(parents=True, exist_ok=True)
        rejects.to_csv(rejects_path, index=False, encoding="utf-8-sig")

    return {
        "database": database,
        "config_file": str(config_path),
        "dataset_name": dataset_name,
        "output_file": str(output_path),
        "rejects_file": str(rejects_path) if rejects_path else None,
        "raw_row_count": int(len(raw)),
        "sample_count": int(len(samples)),
        "reject_count": int(len(rejects)),
        "pump_sample_counts": samples.groupby("pump_id").size().to_dict() if not samples.empty else {},
    }


def build_file(config_path: Path, input_path: Path, output_path: Path, rejects_path: Optional[Path] = None) -> Dict[str, Any]:
    config = read_config(config_path)
    raw = read_table(input_path)
    samples, rejects = build_samples(config, raw)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    samples.to_csv(output_path, index=False, encoding="utf-8-sig")

    if rejects_path:
        rejects_path.parent.mkdir(parents=True, exist_ok=True)
        rejects.to_csv(rejects_path, index=False, encoding="utf-8-sig")

    return {
        "input_file": str(input_path),
        "config_file": str(config_path),
        "output_file": str(output_path),
        "rejects_file": str(rejects_path) if rejects_path else None,
        "raw_row_count": int(len(raw)),
        "sample_count": int(len(samples)),
        "reject_count": int(len(rejects)),
        "pump_sample_counts": samples.groupby("pump_id").size().to_dict() if not samples.empty else {},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build pump regression samples from raw point data.")
    sub = parser.add_subparsers(dest="command", required=True)

    build_parser = sub.add_parser("build", help="Build derived Q/H/w/eta samples.")
    build_parser.add_argument("--config", required=True, type=Path)
    build_parser.add_argument("--input", required=True, type=Path)
    build_parser.add_argument("--output", required=True, type=Path)
    build_parser.add_argument("--rejects", type=Path)

    seed_parser = sub.add_parser("seed-db", help="Create MySQL tables and import variable definitions plus raw point samples.")
    seed_parser.add_argument("--mysql-exe", default=Path("mysql"), type=Path)
    seed_parser.add_argument("--host", default="127.0.0.1")
    seed_parser.add_argument("--port", type=int, default=3306)
    seed_parser.add_argument("--user", required=True)
    seed_parser.add_argument("--password", required=True)
    seed_parser.add_argument("--database", default="pump_curve_model")
    seed_parser.add_argument("--schema", default=Path(__file__).with_name("db_schema.mysql.sql"), type=Path)
    seed_parser.add_argument("--config", required=True, type=Path)
    seed_parser.add_argument("--dataset-name", default="sample_raw_points")
    seed_parser.add_argument("--input", required=True, type=Path)

    seed_demo_parser = sub.add_parser("seed-demo-db", help="Create MySQL tables and import generated demo raw point samples.")
    seed_demo_parser.add_argument("--mysql-exe", default=Path("mysql"), type=Path)
    seed_demo_parser.add_argument("--host", default="127.0.0.1")
    seed_demo_parser.add_argument("--port", type=int, default=3306)
    seed_demo_parser.add_argument("--user", required=True)
    seed_demo_parser.add_argument("--password", required=True)
    seed_demo_parser.add_argument("--database", default="pump_curve_model")
    seed_demo_parser.add_argument("--schema", default=Path(__file__).with_name("db_schema.mysql.sql"), type=Path)
    seed_demo_parser.add_argument("--config", required=True, type=Path)
    seed_demo_parser.add_argument("--dataset-name", default="sample_raw_points")
    seed_demo_parser.add_argument("--sample-count", type=int, default=50)

    build_db_parser = sub.add_parser("build-db", help="Read raw point samples from MySQL and build derived Q/H/w/eta samples.")
    build_db_parser.add_argument("--mysql-exe", default=Path("mysql"), type=Path)
    build_db_parser.add_argument("--host", default="127.0.0.1")
    build_db_parser.add_argument("--port", type=int, default=3306)
    build_db_parser.add_argument("--user", required=True)
    build_db_parser.add_argument("--password", required=True)
    build_db_parser.add_argument("--database", default="pump_curve_model")
    build_db_parser.add_argument("--config", required=True, type=Path)
    build_db_parser.add_argument("--dataset-name", default="sample_raw_points")
    build_db_parser.add_argument("--output", required=True, type=Path)
    build_db_parser.add_argument("--rejects", type=Path)

    args = parser.parse_args()
    if args.command == "build":
        payload = build_file(args.config, args.input, args.output, args.rejects)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "seed-db":
        payload = seed_database(
            args.mysql_exe,
            args.host,
            args.port,
            args.user,
            args.password,
            args.database,
            args.schema,
            args.config,
            args.dataset_name,
            args.input,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "seed-demo-db":
        payload = seed_demo_database(
            args.mysql_exe,
            args.host,
            args.port,
            args.user,
            args.password,
            args.database,
            args.schema,
            args.config,
            args.dataset_name,
            args.sample_count,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.command == "build-db":
        payload = build_from_database(
            args.mysql_exe,
            args.host,
            args.port,
            args.user,
            args.password,
            args.database,
            args.config,
            args.dataset_name,
            args.output,
            args.rejects,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
