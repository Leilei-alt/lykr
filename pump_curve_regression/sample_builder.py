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
  - eta = 0.00275 * Q * H / power, where Q is m3/h, H is m, power is kW.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


DEFAULT_EFFICIENCY_FACTOR = 0.00275
DEFAULT_SPEED_RATIO_TOLERANCE = 0.02
SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def demo_pump_statuses(index: int, group_no: int, period_index: int = 0) -> Tuple[int, int, int]:
    selector = (index + group_no + period_index) % 16
    if selector in {0, 7}:
        return 1, 1, 0
    if selector == 11:
        return 1, 0, 1
    if selector == 14:
        return 0, 1, 1
    return 1, 1, 1


def demo_controller_status(index: int, group_no: int, offset: int, period_index: int = 0) -> int:
    selector = (index + group_no + period_index) % 10
    if offset == 0 and selector == 6:
        return 0
    if offset == 1 and selector in {0, 5}:
        return 0
    return 1


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


def parse_mysql_table(output: str) -> List[Dict[str, str]]:
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) < 2:
        return []
    headers = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        values = line.split("\t")
        rows.append({header: values[index] if index < len(values) else "" for index, header in enumerate(headers)})
    return rows


def quote_identifier(identifier: str) -> str:
    text = str(identifier or "")
    if not SQL_IDENTIFIER_RE.match(text):
        raise ValueError(f"Unsafe SQL identifier from pump_point_index: {text!r}")
    return f"`{text}`"


def read_point_index(
    mysql_exe: Path,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    device_type: str,
    point_roles: List[str],
) -> Dict[str, Dict[str, str]]:
    role_list = ", ".join(sql_quote(role) for role in point_roles)
    sql = f"""
SELECT
  device_type,
  point_name,
  point_role,
  target_table,
  target_column,
  unit,
  data_type
FROM pump_point_index
WHERE active = 1
  AND device_type = {sql_quote(device_type)}
  AND point_role IN ({role_list})
ORDER BY point_role;
"""
    rows = parse_mysql_table(run_mysql(mysql_exe, host, port, user, password, sql, database))
    index = {row["point_role"]: row for row in rows}
    missing = [role for role in point_roles if role not in index]
    if missing:
        raise RuntimeError(f"Missing active point index for {device_type}: {', '.join(missing)}")
    return index


def indexed_target_table(index: Dict[str, Dict[str, str]], roles: List[str]) -> str:
    tables = {index[role]["target_table"] for role in roles}
    if len(tables) != 1:
        raise RuntimeError(f"Point index roles must use one target table, got: {', '.join(sorted(tables))}")
    return quote_identifier(next(iter(tables)))


def indexed_column(index: Dict[str, Dict[str, str]], role: str) -> str:
    return quote_identifier(index[role]["target_column"])


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


def optional_set(values: Optional[List[str]]) -> Optional[set[str]]:
    if not values:
        return None
    return {str(value) for value in values}


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


def read_controller_rows_from_db(
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
    point_index = read_point_index(
        mysql_exe,
        host,
        port,
        user,
        password,
        database,
        "header_controller",
        ["header_controller_flow", "header_controller_status"],
    )
    target_table = indexed_target_table(point_index, ["header_controller_flow", "header_controller_status"])
    flow_column = indexed_column(point_index, "header_controller_flow")
    status_column = indexed_column(point_index, "header_controller_status")
    conditions = [f"dataset_name = {sql_quote(dataset_name)}"]
    if start_time:
        conditions.append(f"sample_time >= {sql_quote(start_time)}")
    if end_time:
        conditions.append(f"sample_time <= {sql_quote(end_time)}")
    sql = f"""
SELECT
  dataset_name,
  sample_time,
  group_id,
  controller_id,
  {flow_column} AS flow_value,
  {status_column} AS status
FROM {target_table}
WHERE {" AND ".join(conditions)}
ORDER BY sample_time, group_id, controller_id;
"""
    output = run_mysql(mysql_exe, host, port, user, password, sql, database)
    rows = []
    for line in output.splitlines():
        if not line.strip() or line.startswith("dataset_name\t"):
            continue
        parts = line.split("\t")
        if len(parts) != 6:
            continue
        rows.append(
            {
                "dataset_name": parts[0],
                "sample_time": parts[1],
                "group_id": parts[2],
                "device_id": parts[3],
                "flow_value": to_float(parts[4]),
                "status": to_float(parts[5]),
            }
        )
    return pd.DataFrame(rows)


def read_chiller_rows_from_db(
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
    point_index = read_point_index(
        mysql_exe,
        host,
        port,
        user,
        password,
        database,
        "chiller",
        ["chiller_flow", "chiller_status"],
    )
    target_table = indexed_target_table(point_index, ["chiller_flow", "chiller_status"])
    flow_column = indexed_column(point_index, "chiller_flow")
    status_column = indexed_column(point_index, "chiller_status")
    flow_point_name = point_index["chiller_flow"]["point_name"]
    conditions = [f"dataset_name = {sql_quote(dataset_name)}"]
    if start_time:
        conditions.append(f"sample_time >= {sql_quote(start_time)}")
    if end_time:
        conditions.append(f"sample_time <= {sql_quote(end_time)}")
    sql = f"""
SELECT
  dataset_name,
  sample_time,
  group_id,
  chiller_id,
  {sql_quote(flow_point_name)} AS flow_point_name,
  {flow_column} AS flow_value,
  {status_column} AS status
FROM {target_table}
WHERE {" AND ".join(conditions)}
ORDER BY sample_time, group_id, chiller_id;
"""
    output = run_mysql(mysql_exe, host, port, user, password, sql, database)
    rows = []
    for line in output.splitlines():
        if not line.strip() or line.startswith("dataset_name\t"):
            continue
        parts = line.split("\t")
        if len(parts) != 7:
            continue
        rows.append(
            {
                "dataset_name": parts[0],
                "sample_time": parts[1],
                "group_id": parts[2],
                "device_id": parts[3],
                "flow_point_name": parts[4],
                "flow_value": to_float(parts[5]),
                "status": to_float(parts[6]),
            }
        )
    return pd.DataFrame(rows)


def read_pump_rows_from_db(
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
    point_index = read_point_index(
        mysql_exe,
        host,
        port,
        user,
        password,
        database,
        "pump",
        ["pump_status", "pump_speed_ratio", "pump_head", "pump_power"],
    )
    target_table = indexed_target_table(point_index, ["pump_status", "pump_speed_ratio", "pump_head", "pump_power"])
    status_column = indexed_column(point_index, "pump_status")
    speed_ratio_column = indexed_column(point_index, "pump_speed_ratio")
    head_column = indexed_column(point_index, "pump_head")
    power_column = indexed_column(point_index, "pump_power")
    conditions = [f"dataset_name = {sql_quote(dataset_name)}"]
    if start_time:
        conditions.append(f"sample_time >= {sql_quote(start_time)}")
    if end_time:
        conditions.append(f"sample_time <= {sql_quote(end_time)}")
    sql = f"""
SELECT
  dataset_name,
  sample_time,
  group_id,
  pump_id,
  {status_column} AS status,
  {speed_ratio_column} AS speed_ratio,
  {head_column} AS head,
  {power_column} AS power_kw
FROM {target_table}
WHERE {" AND ".join(conditions)}
ORDER BY sample_time, group_id, pump_id;
"""
    output = run_mysql(mysql_exe, host, port, user, password, sql, database)
    rows = []
    for line in output.splitlines():
        if not line.strip() or line.startswith("dataset_name\t"):
            continue
        parts = line.split("\t")
        if len(parts) != 8:
            continue
        rows.append(
            {
                "dataset_name": parts[0],
                "sample_time": parts[1],
                "group_id": parts[2],
                "pump_id": parts[3],
                "status": to_float(parts[4]),
                "w": to_float(parts[5]),
                "H": to_float(parts[6]),
                "power": to_float(parts[7]),
            }
        )
    return pd.DataFrame(rows)


def build_grouped_device_samples(
    config: Dict[str, Any],
    controller_rows: pd.DataFrame,
    chiller_rows: pd.DataFrame,
    pump_rows: pd.DataFrame,
    source_types: Optional[List[str]] = None,
    group_ids: Optional[List[str]] = None,
    pump_ids: Optional[List[str]] = None,
    flow_device_ids: Optional[List[str]] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    defaults = config.get("defaults", {})
    efficiency_factor = float(defaults.get("efficiency_factor", DEFAULT_EFFICIENCY_FACTOR))
    speed_tolerance = float(defaults.get("speed_ratio_tolerance", DEFAULT_SPEED_RATIO_TOLERANCE))
    filters = valid_filters(config)
    selected_sources = optional_set(source_types)
    selected_groups = optional_set(group_ids)
    selected_pumps = optional_set(pump_ids)
    selected_flow_devices = optional_set(flow_device_ids)

    source_frames = [
        ("header_controller", controller_rows),
        ("chiller", chiller_rows),
    ]
    samples: List[Dict[str, Any]] = []
    issues: List[BuildIssue] = []

    for source_type, flow_rows in source_frames:
        if selected_sources and source_type not in selected_sources:
            continue
        if flow_rows.empty:
            continue

        working_flow = flow_rows.copy()
        working_flow = working_flow[working_flow["flow_value"].notna()]
        working_flow = working_flow[working_flow["flow_value"] > 0]
        if "status" in working_flow.columns:
            working_flow = working_flow[working_flow["status"].fillna(1) > 0]
        if selected_groups:
            working_flow = working_flow[working_flow["group_id"].astype(str).isin(selected_groups)]
        if selected_flow_devices:
            working_flow = working_flow[working_flow["device_id"].astype(str).isin(selected_flow_devices)]

        for (sample_time, group_id), group_flow_rows in working_flow.groupby(["sample_time", "group_id"], sort=True):
            q_total = float(group_flow_rows["flow_value"].sum())
            if q_total <= 0:
                issues.append(BuildIssue(str(sample_time), str(group_id), None, f"{source_type} Q_total <= 0"))
                continue

            group_pumps = pump_rows[
                (pump_rows["sample_time"].astype(str) == str(sample_time))
                & (pump_rows["group_id"].astype(str) == str(group_id))
            ].copy()
            group_pumps = group_pumps[group_pumps["status"].fillna(0) > 0]
            if group_pumps.empty:
                issues.append(BuildIssue(str(sample_time), str(group_id), None, f"{source_type} no running pump in same group"))
                continue
            if selected_pumps and not group_pumps["pump_id"].astype(str).isin(selected_pumps).any():
                continue

            w_values = group_pumps["w"].dropna().astype(float)
            if len(w_values) != len(group_pumps):
                issues.append(BuildIssue(str(sample_time), str(group_id), None, f"{source_type} pump speed ratio is missing"))
                continue
            speed_span = float(w_values.max() - w_values.min()) if len(w_values) > 1 else 0.0
            if speed_span > speed_tolerance:
                issues.append(
                    BuildIssue(
                        str(sample_time),
                        str(group_id),
                        None,
                        f"{source_type} speed ratio span {speed_span:.4f} > {speed_tolerance:.4f}",
                    )
                )
                continue

            q_each = q_total / len(group_pumps)
            for _, pump in group_pumps.iterrows():
                pump_id = str(pump["pump_id"])
                if selected_pumps and pump_id not in selected_pumps:
                    continue
                h = to_float(pump.get("H"))
                power = to_float(pump.get("power"))
                w = to_float(pump.get("w"))
                eta = None
                if h is not None and power is not None and power > 0:
                    eta = efficiency_factor * q_each * h / power

                sample = {
                    "timestamp": str(sample_time),
                    "group_id": str(group_id),
                    "side": source_type,
                    "source_type": source_type,
                    "source_device_count": int(len(group_flow_rows)),
                    "source_device_ids": ",".join(sorted(group_flow_rows["device_id"].astype(str).unique().tolist())),
                    "pump_id": pump_id,
                    "status": 1,
                    "pump_status": 1,
                    "facility_running_count": int(len(group_flow_rows)),
                    "pump_running_count": int(len(group_pumps)),
                    "Q_total": q_total,
                    "Q": q_each,
                    "H": h,
                    "power": power,
                    "frequency": None,
                    "rated_frequency": None,
                    "w": w,
                    "eta": eta,
                    "Q_source": source_type,
                    "H_source": "pump_device_values.head",
                    "w_source": "pump_device_values.speed_ratio",
                    "eta_source": f"eta = {efficiency_factor} * Q * H / power",
                    "allocation_method": "equal_after_speed_ratio_check",
                    "speed_ratio_span": speed_span,
                }

                ok, reason = passes_filters(sample, filters)
                if ok:
                    sample["quality_flag"] = "valid"
                    samples.append(sample)
                else:
                    issues.append(BuildIssue(str(sample_time), str(group_id), pump_id, reason or "invalid sample"))

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


def generate_demo_separated_device_rows(sample_count: int = 50) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    raw = generate_demo_raw_points(sample_count)
    controller_rows: List[Dict[str, Any]] = []
    chiller_rows: List[Dict[str, Any]] = []
    pump_rows: List[Dict[str, Any]] = []

    for i, row in raw.iterrows():
        sample_time = row["timestamp"]
        phase = i / max(sample_count - 1, 1)

        for group_no in range(1, 4):
            header_group = f"header_group_{group_no}"
            header_total = (220 + 420 * phase + 18 * math.sin(i * 0.28 + group_no)) * (1 + 0.08 * (group_no - 1))
            controller_split = 0.50 + 0.03 * math.sin(i * 0.23 + group_no * 0.7)
            controller_start = (group_no - 1) * 2 + 1
            pump_start = (group_no - 1) * 2 + 1
            pump_indices = [pump_start, pump_start + 1, 6 + group_no]
            w_base = min(0.98, 0.70 + 0.23 * phase + 0.018 * (group_no - 1) + 0.006 * math.sin(i * 0.18 + group_no))
            speed_delta = 0.026 if (i + group_no) % 19 == 0 else 0.006
            statuses = demo_pump_statuses(i, group_no)

            for offset, ratio in enumerate([controller_split, 1 - controller_split]):
                controller_rows.append(
                    {
                        "sample_time": sample_time,
                        "group_id": header_group,
                        "controller_id": f"HCC{controller_start + offset}",
                        "flow_value": round(header_total * ratio, 3),
                        "status": demo_controller_status(i, group_no, offset),
                    }
                )

            for offset, pump_index in enumerate(pump_indices):
                pump_rows.append(
                    {
                        "sample_time": sample_time,
                        "group_id": header_group,
                        "pump_id": f"CHWP{pump_index}",
                        "status": statuses[offset],
                        "speed_ratio": round(w_base + (offset - 1) * speed_delta, 4),
                        "head": round(30 + 15 * phase + 1.4 * (group_no - 1) + 0.7 * math.sin(i * 0.21 + offset), 3),
                        "power_kw": round(34 + 43 * phase + 3.5 * (group_no - 1) + 1.1 * math.cos(i * 0.19 + offset), 3),
                    }
                )

        for group_no in range(1, 4):
            chiller_group = f"chiller_group_{group_no}"
            chiller_start = (group_no - 1) * 3 + 1
            pump_start = (group_no - 1) * 2 + 1
            pump_indices = [pump_start, pump_start + 1, 6 + group_no]
            w_base = min(0.98, 0.71 + 0.22 * phase + 0.016 * (group_no - 1) + 0.006 * math.cos(i * 0.16 + group_no))
            speed_delta = 0.028 if (i + group_no) % 23 == 0 else 0.007
            statuses = demo_pump_statuses(i, group_no)

            for offset in range(3):
                chiller_index = chiller_start + offset
                status = 1 if offset == 0 or i >= sample_count * offset // 3 else 0
                base_flow = 245 + 155 * phase + 26 * offset + 16 * (group_no - 1)
                chiller_rows.append(
                    {
                        "sample_time": sample_time,
                        "group_id": chiller_group,
                        "chiller_id": f"CH{chiller_index}",
                        "flow_value": round(base_flow + 9 * math.sin(i * 0.31 + offset + group_no), 3),
                        "status": status,
                    }
                )

            for offset, pump_index in enumerate(pump_indices):
                pump_rows.append(
                    {
                        "sample_time": sample_time,
                        "group_id": chiller_group,
                        "pump_id": f"CWP{pump_index}",
                        "status": statuses[offset],
                        "speed_ratio": round(w_base + (offset - 1) * speed_delta, 4),
                        "head": round(25 + 12.5 * phase + 1.2 * (group_no - 1) + 0.6 * math.cos(i * 0.22 + offset), 3),
                        "power_kw": round(33 + 41 * phase + 3.2 * (group_no - 1) + 1.0 * math.sin(i * 0.2 + offset), 3),
                    }
                )

    return pd.DataFrame(controller_rows), pd.DataFrame(chiller_rows), pd.DataFrame(pump_rows)


def seed_separated_device_values(
    mysql_exe: Path,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    dataset_name: str,
    controller_rows: pd.DataFrame,
    chiller_rows: pd.DataFrame,
    pump_rows: pd.DataFrame,
) -> Dict[str, int]:
    statements = [
        f"DELETE FROM pump_header_controller_values WHERE dataset_name = {sql_quote(dataset_name)};",
        f"DELETE FROM pump_chiller_values WHERE dataset_name = {sql_quote(dataset_name)};",
        f"DELETE FROM pump_device_values WHERE dataset_name = {sql_quote(dataset_name)};",
    ]

    controller_values = []
    for _, row in controller_rows.iterrows():
        controller_values.append(
            "("
            f"{sql_quote(dataset_name)}, {sql_quote(row['sample_time'])}, {sql_quote(row['group_id'])}, "
            f"{sql_quote(row['controller_id'])}, "
            f"{repr(float(row['flow_value']))}, {int(row['status'])}"
            ")"
        )
    if controller_values:
        statements.append(
            """
INSERT INTO pump_header_controller_values
  (dataset_name, sample_time, group_id, controller_id, flow_value, status)
VALUES
"""
            + ",\n".join(controller_values)
            + """
ON DUPLICATE KEY UPDATE
  group_id = VALUES(group_id),
  flow_value = VALUES(flow_value),
  status = VALUES(status);
"""
        )

    chiller_values = []
    for _, row in chiller_rows.iterrows():
        chiller_values.append(
            "("
            f"{sql_quote(dataset_name)}, {sql_quote(row['sample_time'])}, {sql_quote(row['group_id'])}, "
            f"{sql_quote(row['chiller_id'])}, "
            f"{repr(float(row['flow_value']))}, {int(row['status'])}"
            ")"
        )
    if chiller_values:
        statements.append(
            """
INSERT INTO pump_chiller_values
  (dataset_name, sample_time, group_id, chiller_id, flow_value, status)
VALUES
"""
            + ",\n".join(chiller_values)
            + """
ON DUPLICATE KEY UPDATE
  group_id = VALUES(group_id),
  flow_value = VALUES(flow_value),
  status = VALUES(status);
"""
        )

    pump_values = []
    for _, row in pump_rows.iterrows():
        pump_values.append(
            "("
            f"{sql_quote(dataset_name)}, {sql_quote(row['sample_time'])}, {sql_quote(row['group_id'])}, "
            f"{sql_quote(row['pump_id'])}, {int(row['status'])}, {repr(float(row['speed_ratio']))}, "
            f"{repr(float(row['head']))}, {repr(float(row['power_kw']))}"
            ")"
        )
    if pump_values:
        statements.append(
            """
INSERT INTO pump_device_values
  (dataset_name, sample_time, group_id, pump_id, status, speed_ratio, head, power_kw)
VALUES
"""
            + ",\n".join(pump_values)
            + """
ON DUPLICATE KEY UPDATE
  group_id = VALUES(group_id),
  status = VALUES(status),
  speed_ratio = VALUES(speed_ratio),
  head = VALUES(head),
  power_kw = VALUES(power_kw);
"""
        )

    run_mysql(mysql_exe, host, port, user, password, "\n".join(statements), database)
    return {
        "controller_row_count": int(len(controller_rows)),
        "chiller_row_count": int(len(chiller_rows)),
        "pump_row_count": int(len(pump_rows)),
    }


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

    seed_separated_demo_parser = sub.add_parser("seed-separated-demo-db", help="Create MySQL tables and import demo rows into separated device tables.")
    seed_separated_demo_parser.add_argument("--mysql-exe", default=Path("mysql"), type=Path)
    seed_separated_demo_parser.add_argument("--host", default="127.0.0.1")
    seed_separated_demo_parser.add_argument("--port", type=int, default=3306)
    seed_separated_demo_parser.add_argument("--user", required=True)
    seed_separated_demo_parser.add_argument("--password", required=True)
    seed_separated_demo_parser.add_argument("--database", default="pump_curve_model")
    seed_separated_demo_parser.add_argument("--schema", default=Path(__file__).with_name("db_schema.mysql.sql"), type=Path)
    seed_separated_demo_parser.add_argument("--config", required=True, type=Path)
    seed_separated_demo_parser.add_argument("--dataset-name", default="sample_raw_points")
    seed_separated_demo_parser.add_argument("--sample-count", type=int, default=50)

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
    elif args.command == "seed-separated-demo-db":
        config = read_config(args.config)
        ensure_schema(args.mysql_exe, args.host, args.port, args.user, args.password, args.schema)
        variables = collect_variables(config)
        seed_variables(args.mysql_exe, args.host, args.port, args.user, args.password, args.database, variables)
        controller_rows, chiller_rows, pump_rows = generate_demo_separated_device_rows(args.sample_count)
        counts = seed_separated_device_values(
            args.mysql_exe,
            args.host,
            args.port,
            args.user,
            args.password,
            args.database,
            args.dataset_name,
            controller_rows,
            chiller_rows,
            pump_rows,
        )
        print(
            json.dumps(
                {
                    "database": args.database,
                    "config_file": str(args.config),
                    "dataset_name": args.dataset_name,
                    "variable_count": len(variables),
                    **counts,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
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
