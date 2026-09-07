#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import os
import json
import urllib.error
import urllib.request
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).resolve().parents[2]
REGRESSION_DIR = ROOT_DIR / "pump_curve_regression"
CONFIG_PATH = ROOT_DIR / "pump_model_config" / "pump_model_config.template.json"
COP_ASSET_DIR = ROOT_DIR / "COP_FIT_20260818" / "html" / "assets"
STATIC_DIR = Path(__file__).resolve().parent / "static"

sys.path.insert(0, str(REGRESSION_DIR))

from pump_curve_regression import (  # noqa: E402
    fit_one_pump,
    predict_quadratic,
    representative_speed_ratios,
)
from sample_builder import (  # noqa: E402
    build_grouped_device_samples,
    read_config,
    run_mysql,
    sql_quote,
)


class MysqlSettings(BaseModel):
    mysql_exe: str = "G:\\mysql-8.0.46-winx64\\bin\\mysql.exe"
    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "root"
    password: str = "wdlwdl123."
    database: str = "pump_curve_model"


class CpnMysqlSettings(BaseModel):
    mysql_exe: str = "G:\\mysql-8.0.46-winx64\\bin\\mysql.exe"
    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "root"
    password: str = "wdlwdl123."
    database: str = "ly_czwxc"
    table: str = "ly_cpn"


class InfluxSettings(BaseModel):
    url: str = "http://127.0.0.1:8086"
    token: str = "aeALbvY_ikDyDa0s1UiljrkavEAjToUUznM82-CZFnYWGV2XdrlynZL8vYLM8pFEoOyFyS-Fndshb8vSuZ_zxg=="
    org: str = "lynkros"
    bucket: str = "czwxc_1"
    aggregate_window: str = "5m"
    timezone: str = "Asia/Shanghai"
    type_code_format: str = "decimal"
    point_code_include_0x: bool = True


class RegressionRequest(BaseModel):
    dataset_name: str = "sample_raw_points"
    start_time: str
    end_time: str
    side: str = ""
    source_types: List[str] = Field(default_factory=list)
    group_ids: List[str] = Field(default_factory=list)
    flow_device_ids: List[str] = Field(default_factory=list)
    facility_ids: List[str] = Field(default_factory=list)
    pump_ids: List[str] = Field(default_factory=list)
    min_samples: int = 10


app = FastAPI(title="Pump Curve Regression API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
if COP_ASSET_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(COP_ASSET_DIR)), name="assets")

DEVICE_TYPE_CHILLER = 32
DEVICE_TYPE_PUMP = 36
DEVICE_TYPE_HEADER = 38

SOURCE_TYPE_BY_CPN_TYPE = {
    DEVICE_TYPE_CHILLER: "chiller",
    DEVICE_TYPE_HEADER: "header_controller",
}

INFLUX_POINTS = {
    "status": "0x00000200",
    "pump_speed_ratio": "0x00000210",
    "pump_head": "0x00000212",
    "pump_power": "0x00000220",
    "chiller_flow": "0x0000021D",
    "header_flow": "0x0000024A",
}


def mysql_settings() -> MysqlSettings:
    return MysqlSettings()


def cpn_mysql_settings() -> CpnMysqlSettings:
    return CpnMysqlSettings(
        mysql_exe=os.getenv("PUMP_CPN_MYSQL_EXE", CpnMysqlSettings().mysql_exe),
        host=os.getenv("PUMP_CPN_MYSQL_HOST", CpnMysqlSettings().host),
        port=int(os.getenv("PUMP_CPN_MYSQL_PORT", str(CpnMysqlSettings().port))),
        user=os.getenv("PUMP_CPN_MYSQL_USER", CpnMysqlSettings().user),
        password=os.getenv("PUMP_CPN_MYSQL_PASSWORD", CpnMysqlSettings().password),
        database=os.getenv("PUMP_CPN_MYSQL_DATABASE", CpnMysqlSettings().database),
        table=os.getenv("PUMP_CPN_MYSQL_TABLE", CpnMysqlSettings().table),
    )


def influx_settings() -> InfluxSettings:
    return InfluxSettings(
        url=os.getenv("PUMP_INFLUX_URL", InfluxSettings().url),
        token=os.getenv("PUMP_INFLUX_TOKEN", InfluxSettings().token),
        org=os.getenv("PUMP_INFLUX_ORG", InfluxSettings().org),
        bucket=os.getenv("PUMP_INFLUX_BUCKET", InfluxSettings().bucket),
        aggregate_window=os.getenv("PUMP_INFLUX_AGGREGATE_WINDOW", InfluxSettings().aggregate_window),
        timezone=os.getenv("PUMP_INFLUX_TIMEZONE", InfluxSettings().timezone),
        type_code_format=os.getenv("PUMP_INFLUX_TYPE_CODE_FORMAT", InfluxSettings().type_code_format),
        point_code_include_0x=os.getenv("PUMP_INFLUX_POINT_INCLUDE_0X", "1").lower() in {"1", "true", "yes"},
    )


def mysql_output_rows(sql: str) -> List[Dict[str, str]]:
    settings = mysql_settings()
    return parse_mysql_rows(
        run_mysql(
            Path(settings.mysql_exe),
            settings.host,
            settings.port,
            settings.user,
            settings.password,
            sql,
            settings.database,
        )
    )


def cpn_mysql_output_rows(sql: str) -> List[Dict[str, str]]:
    settings = cpn_mysql_settings()
    return parse_mysql_rows(
        run_mysql(
            Path(settings.mysql_exe),
            settings.host,
            settings.port,
            settings.user,
            settings.password,
            sql,
            settings.database,
        )
    )


def sql_identifier(value: str) -> str:
    text = str(value or "")
    if not text.replace("_", "").isalnum():
        raise HTTPException(status_code=500, detail=f"不安全的数据库标识符: {text}")
    return f"`{text}`"


def utc_flux_time(value: str) -> str:
    settings = influx_settings()
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(settings.timezone))
    return dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")


def flux_string(value: Any) -> str:
    text = str(value)
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def sql_string(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def sql_quoted_identifier(value: Any) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def measurement_name(cpn_type: int, point_name: str) -> str:
    settings = influx_settings()
    type_code = f"{cpn_type:02X}" if settings.type_code_format.lower() == "hex" else f"{cpn_type:02d}"
    point_code = point_name if settings.point_code_include_0x else point_name.replace("0x", "")
    return f"ly_{type_code}_FFFFFFFF_{point_code}"


def query_cpn_catalog() -> pd.DataFrame:
    settings = cpn_mysql_settings()
    table_name = sql_identifier(settings.table)
    try:
        column_rows = cpn_mysql_output_rows(f"SHOW COLUMNS FROM {table_name};")
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=f"无法读取 MySQL 设备目录表结构 {settings.table}: {exc}") from exc

    columns = {row.get("Field") for row in column_rows}
    required = {"cpn_type", "group_id", "show_name", "true_cpn_name"}
    missing = sorted(required - columns)
    if missing:
        raise HTTPException(status_code=500, detail=f"MySQL 设备目录 {settings.table} 缺少字段: {', '.join(missing)}")

    id_expr = "CAST(id AS CHAR) AS id" if "id" in columns else "CAST(true_cpn_name AS CHAR) AS id"
    cpn_name_expr = "cpn_name" if "cpn_name" in columns else "true_cpn_name AS cpn_name"
    is_show_expr = "CAST(is_show AS CHAR) AS is_show" if "is_show" in columns else "NULL AS is_show"
    order_tail = ", id" if "id" in columns else ", true_cpn_name"
    sql = f"""
SELECT
  {id_expr},
  {cpn_name_expr},
  CAST(cpn_type AS CHAR) AS cpn_type,
  CAST(group_id AS CHAR) AS group_id,
  show_name,
  true_cpn_name,
  {is_show_expr}
FROM {table_name}
WHERE cpn_type IN ({DEVICE_TYPE_CHILLER}, {DEVICE_TYPE_PUMP}, {DEVICE_TYPE_HEADER})
  AND group_id IS NOT NULL
  AND true_cpn_name IS NOT NULL
  AND true_cpn_name <> ''
ORDER BY group_id, cpn_type{order_tail};
"""
    try:
        rows = cpn_mysql_output_rows(sql)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=f"无法读取 MySQL 设备目录 ly_cpn: {exc}") from exc

    records = []
    for row in rows:
        cpn_type = finite_float(row.get("cpn_type"))
        if cpn_type is None:
            continue
        records.append(
            {
                "id": row.get("id"),
                "cpn_name": row.get("cpn_name"),
                "cpn_type": int(cpn_type),
                "group_id": str(row.get("group_id")),
                "show_name": row.get("show_name") or row.get("cpn_name") or row.get("true_cpn_name"),
                "true_cpn_name": row.get("true_cpn_name") or row.get("cpn_name"),
                "is_show": row.get("is_show"),
            }
        )
    return pd.DataFrame(records)


def computable_catalog(catalog: pd.DataFrame) -> pd.DataFrame:
    if catalog.empty:
        return catalog
    counts = catalog.groupby(["group_id", "cpn_type"]).size().unstack(fill_value=0)
    group_ids = [
        group_id
        for group_id, row in counts.iterrows()
        if int(row.get(DEVICE_TYPE_PUMP, 0)) > 0
        and (int(row.get(DEVICE_TYPE_CHILLER, 0)) > 0 or int(row.get(DEVICE_TYPE_HEADER, 0)) > 0)
    ]
    return catalog[catalog["group_id"].astype(str).isin([str(item) for item in group_ids])].copy()


def query_influx_points(
    cpn_names: Sequence[str],
    measurements: Sequence[str],
    start_time: str,
    end_time: str,
) -> pd.DataFrame:
    if not cpn_names or not measurements:
        return pd.DataFrame(columns=["sample_time", "device_id", "measurement", "value"])

    settings = influx_settings()
    cpn_filter = ", ".join(sql_string(item) for item in sorted(set(cpn_names)))
    start_utc = utc_flux_time(start_time)
    end_utc = utc_flux_time(end_time)
    query_parts = [
        f"""
SELECT
  time AS sample_time,
  cpn_name AS device_id,
  {sql_string(measurement)} AS measurement,
  value
FROM {sql_quoted_identifier(measurement)}
WHERE cpn_name IN ({cpn_filter})
  AND time >= {sql_string(start_utc)}
  AND time <= {sql_string(end_utc)}
"""
        for measurement in sorted(set(measurements))
    ]
    query = "\nUNION ALL\n".join(query_parts)
    payload = json.dumps({"db": settings.bucket, "q": query}).encode("utf-8")
    request = urllib.request.Request(
        f"{settings.url.rstrip('/')}/api/v3/query_sql",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Token {settings.token}",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            rows = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=500, detail=f"无法读取 InfluxDB 数据: HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"无法读取 InfluxDB 数据: {exc}") from exc

    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["sample_time", "device_id", "measurement", "value"])

    frame["sample_time"] = pd.to_datetime(frame["sample_time"], utc=True).dt.tz_convert(settings.timezone).dt.tz_localize(None)
    frame["sample_time"] = frame["sample_time"].dt.strftime("%Y-%m-%d %H:%M:%S")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    return frame[["sample_time", "device_id", "measurement", "value"]]


def value_frame_for_devices(devices: pd.DataFrame, point_names: Sequence[str], start_time: str, end_time: str) -> pd.DataFrame:
    if devices.empty:
        return pd.DataFrame()
    measurements = [
        measurement_name(int(cpn_type), point_name)
        for cpn_type in devices["cpn_type"].dropna().unique()
        for point_name in point_names
    ]
    values = query_influx_points(
        devices["true_cpn_name"].dropna().astype(str).unique().tolist(),
        measurements,
        start_time,
        end_time,
    )
    if values.empty:
        return pd.DataFrame()
    device_map = devices.set_index("true_cpn_name")[["group_id", "show_name", "cpn_name", "cpn_type"]].to_dict("index")
    values["group_id"] = values["device_id"].map(lambda item: device_map.get(item, {}).get("group_id"))
    values["show_name"] = values["device_id"].map(lambda item: device_map.get(item, {}).get("show_name") or item)
    values["cpn_name"] = values["device_id"].map(lambda item: device_map.get(item, {}).get("cpn_name") or item)
    return values


def pivot_device_values(values: pd.DataFrame, role_by_measurement: Dict[str, str]) -> pd.DataFrame:
    if values.empty:
        return pd.DataFrame()
    mapped = values.copy()
    mapped["role"] = mapped["measurement"].map(role_by_measurement)
    mapped = mapped[mapped["role"].notna()]
    if mapped.empty:
        return pd.DataFrame()
    pivot = mapped.pivot_table(
        index=["sample_time", "group_id", "device_id", "show_name", "cpn_name"],
        columns="role",
        values="value",
        aggfunc="last",
    ).reset_index()
    pivot.columns.name = None
    return pivot


def real_source_rows(start_time: str, end_time: str) -> Dict[str, pd.DataFrame]:
    catalog = computable_catalog(query_cpn_catalog())
    if catalog.empty:
        raise HTTPException(status_code=400, detail="MySQL ly_cpn 中没有可计算的组：每组必须同时包含水泵和冷机/干管协调器")

    controller_devices = catalog[catalog["cpn_type"] == DEVICE_TYPE_HEADER].copy()
    chiller_devices = catalog[catalog["cpn_type"] == DEVICE_TYPE_CHILLER].copy()
    pump_devices = catalog[catalog["cpn_type"] == DEVICE_TYPE_PUMP].copy()

    controller_roles = {
        measurement_name(DEVICE_TYPE_HEADER, INFLUX_POINTS["status"]): "status",
        measurement_name(DEVICE_TYPE_HEADER, INFLUX_POINTS["header_flow"]): "flow_value",
    }
    chiller_roles = {
        measurement_name(DEVICE_TYPE_CHILLER, INFLUX_POINTS["status"]): "status",
        measurement_name(DEVICE_TYPE_CHILLER, INFLUX_POINTS["chiller_flow"]): "flow_value",
    }
    pump_roles = {
        measurement_name(DEVICE_TYPE_PUMP, INFLUX_POINTS["status"]): "status",
        measurement_name(DEVICE_TYPE_PUMP, INFLUX_POINTS["pump_speed_ratio"]): "w",
        measurement_name(DEVICE_TYPE_PUMP, INFLUX_POINTS["pump_head"]): "H",
        measurement_name(DEVICE_TYPE_PUMP, INFLUX_POINTS["pump_power"]): "power",
    }

    controller_rows = pivot_device_values(
        value_frame_for_devices(controller_devices, [INFLUX_POINTS["status"], INFLUX_POINTS["header_flow"]], start_time, end_time),
        controller_roles,
    )
    chiller_rows = pivot_device_values(
        value_frame_for_devices(chiller_devices, [INFLUX_POINTS["status"], INFLUX_POINTS["chiller_flow"]], start_time, end_time),
        chiller_roles,
    )
    pump_rows = pivot_device_values(
        value_frame_for_devices(
            pump_devices,
            [INFLUX_POINTS["status"], INFLUX_POINTS["pump_speed_ratio"], INFLUX_POINTS["pump_head"], INFLUX_POINTS["pump_power"]],
            start_time,
            end_time,
        ),
        pump_roles,
    )

    if not controller_rows.empty:
        controller_rows["source_type"] = "header_controller"
    if not chiller_rows.empty:
        chiller_rows["source_type"] = "chiller"
    if not pump_rows.empty:
        pump_rows = pump_rows.rename(columns={"device_id": "pump_id"})
        pump_rows["source_type"] = "pump"

    controller_rows = ensure_columns(
        controller_rows,
        ["sample_time", "group_id", "device_id", "show_name", "cpn_name", "status", "flow_value", "source_type"],
    )
    chiller_rows = ensure_columns(
        chiller_rows,
        ["sample_time", "group_id", "device_id", "show_name", "cpn_name", "status", "flow_value", "source_type"],
    )
    pump_rows = ensure_columns(
        pump_rows,
        ["sample_time", "group_id", "pump_id", "show_name", "cpn_name", "status", "w", "H", "power", "source_type"],
    )

    return {
        "catalog": catalog,
        "controller_rows": controller_rows,
        "chiller_rows": chiller_rows,
        "pump_rows": pump_rows,
    }


def ensure_columns(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=list(columns))
    result = frame.copy()
    for column in columns:
        if column not in result.columns:
            result[column] = np.nan
    return result


def config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise HTTPException(status_code=500, detail=f"配置文件不存在: {CONFIG_PATH}")
    return read_config(CONFIG_PATH)


def infer_groups_and_sources_for_pumps(
    selected_pump_ids: List[str],
    controller_rows,
    chiller_rows,
    pump_rows,
) -> Dict[str, List[str]]:
    selected = {str(pump_id) for pump_id in selected_pump_ids}
    selected_pump_rows = pump_rows[pump_rows["pump_id"].astype(str).isin(selected)].copy()
    if selected_pump_rows.empty:
        raise HTTPException(status_code=400, detail="选中的水泵在当前时间段内没有数据")

    group_ids = sorted(selected_pump_rows["group_id"].dropna().astype(str).unique().tolist())
    if not group_ids:
        raise HTTPException(status_code=400, detail="选中的水泵没有可用组号")

    source_types = []
    if not controller_rows.empty and controller_rows["group_id"].astype(str).isin(group_ids).any():
        source_types.append("header_controller")
    if not chiller_rows.empty and chiller_rows["group_id"].astype(str).isin(group_ids).any():
        source_types.append("chiller")
    if not source_types:
        raise HTTPException(status_code=400, detail="未找到与所选水泵同组的干管协调控制器或冷机流量数据")

    return {"group_ids": group_ids, "source_types": source_types}


def normalize_datetime(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"时间格式错误: {value}") from exc


def side_groups(cfg: Dict[str, Any], side: str) -> List[Dict[str, Any]]:
    groups = [group for group in cfg.get("pump_groups", []) if group.get("side") == side]
    if not groups:
        raise HTTPException(status_code=400, detail=f"配置中不存在该侧: {side}")
    return groups


def apply_ui_status_selection(raw, groups: List[Dict[str, Any]], facility_ids: List[str], pump_ids: List[str]) -> None:
    selected_facilities = set(facility_ids)
    selected_pumps = set(pump_ids)
    for group in groups:
        for facility in group.get("facilities", []):
            status_point = facility.get("status")
            if status_point and status_point in raw.columns:
                raw.loc[:, status_point] = 1 if facility.get("id") in selected_facilities else 0
        for pump in group.get("pumps", []):
            status_point = pump.get("status")
            if status_point and status_point in raw.columns:
                raw.loc[:, status_point] = 1 if pump.get("id") in selected_pumps else 0


def filtered_config_for_request(cfg: Dict[str, Any], request: RegressionRequest) -> Dict[str, Any]:
    groups = side_groups(cfg, request.side)
    filtered = dict(cfg)
    filtered["pump_groups"] = groups
    return filtered


def finite_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def timestamp_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            text = value.isoformat()
        except ValueError:
            return None
        return None if text in {"NaT", "nan"} else text
    text = str(value)
    return None if text in {"", "NaT", "nan", "None"} else text


def scatter_points(samples, x_col: str, y_col: str) -> List[List[Any]]:
    points: List[List[Any]] = []
    for _, row in samples.iterrows():
        x_value = finite_float(row.get(x_col))
        y_value = finite_float(row.get(y_col))
        w_value = finite_float(row.get("w"))
        if x_value is None or y_value is None or w_value is None:
            continue
        points.append([x_value, y_value, w_value, timestamp_text(row.get("timestamp"))])
    return points


def line_points(x_values: np.ndarray, y_values: np.ndarray) -> List[List[float]]:
    points: List[List[float]] = []
    for x_value, y_value in zip(x_values, y_values):
        x_number = finite_float(x_value)
        y_number = finite_float(y_value)
        if x_number is not None and y_number is not None:
            points.append([x_number, y_number])
    return points


def parse_mysql_rows(output: str) -> List[Dict[str, str]]:
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) < 2:
        return []
    headers = lines[0].split("\t")
    rows: List[Dict[str, str]] = []
    for line in lines[1:]:
        values = line.split("\t")
        rows.append({header: values[index] if index < len(values) else "" for index, header in enumerate(headers)})
    return rows


def row_float(row: Dict[str, str], key: str) -> Optional[float]:
    value = row.get(key)
    if value in {None, "", "NULL"}:
        return None
    return finite_float(value)


@lru_cache(maxsize=256)
def pump_theory_aliases(pump_id: str) -> tuple[str, ...]:
    aliases = [str(pump_id)]
    try:
        catalog = query_cpn_catalog()
    except HTTPException:
        return tuple(aliases)
    if catalog.empty:
        return tuple(aliases)

    mask = pd.Series(False, index=catalog.index)
    for column in ["true_cpn_name", "cpn_name", "show_name"]:
        if column in catalog.columns:
            mask = mask | (catalog[column].astype(str) == str(pump_id))
    for column in ["true_cpn_name", "cpn_name", "show_name"]:
        if column not in catalog.columns:
            continue
        for value in catalog.loc[mask, column].dropna().astype(str).tolist():
            if value and value not in aliases:
                aliases.append(value)
    return tuple(aliases)


def query_theory_curves(pump_id: str, side: Optional[str], group_id: Optional[str]) -> Dict[str, List[Dict[str, Any]]]:
    settings = mysql_settings()
    group_filter = "1 = 1"
    if group_id:
        group_filter = f"(s.group_id IS NULL OR s.group_id = {sql_quote(group_id)})"
    pump_filter = ", ".join(sql_quote(alias) for alias in pump_theory_aliases(pump_id))
    sql = f"""
SELECT
  s.id AS curve_set_id,
  s.curve_name,
  s.source_type,
  s.speed_ratio,
  s.is_normalized,
  p.point_index,
  p.q,
  p.h,
  p.eta,
  p.w,
  p.q_eq,
  p.h_eq
FROM pump_theory_curve_sets AS s
JOIN pump_theory_curve_points AS p ON p.curve_set_id = s.id
WHERE s.active = 1
  AND s.pump_id IN ({pump_filter})
  AND s.side = {sql_quote(side or "unknown")}
  AND {group_filter}
ORDER BY s.id, p.point_index;
"""
    try:
        rows = parse_mysql_rows(
            run_mysql(
                Path(settings.mysql_exe),
                settings.host,
                settings.port,
                settings.user,
                settings.password,
                sql,
                settings.database,
            )
        )
    except RuntimeError:
        return {"head": [], "efficiency": []}

    grouped: Dict[str, List[Dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["curve_set_id"], []).append(row)

    head_lines: List[Dict[str, Any]] = []
    efficiency_lines: List[Dict[str, Any]] = []
    for curve_rows in grouped.values():
        first = curve_rows[0]
        curve_name = first.get("curve_name") or "理论曲线"
        head_points = []
        efficiency_points = []
        for row in curve_rows:
            q_eq = row_float(row, "q_eq")
            h_eq = row_float(row, "h_eq")
            eta = row_float(row, "eta")
            if q_eq is None:
                continue
            if h_eq is not None:
                head_points.append([q_eq, h_eq])
            if eta is not None:
                efficiency_points.append([q_eq, eta])
        if head_points:
            head_lines.append(
                {
                    "name": f"{curve_name}扬程",
                    "points": head_points,
                    "line_type": "dashed",
                }
            )
        if efficiency_points:
            efficiency_lines.append(
                {
                    "name": f"{curve_name}能效",
                    "points": efficiency_points,
                    "line_type": "dashed",
                }
            )
    return {"head": head_lines, "efficiency": efficiency_lines}


def build_scatter_only_chart_data(samples) -> Dict[str, Any]:
    q_eq = samples["Q"] / samples["w"]
    h_eq = samples["H"] / (samples["w"] ** 2)
    scatter_df = samples.copy()
    scatter_df["Q_eq"] = q_eq
    scatter_df["H_eq"] = h_eq

    return {
        "head_normalized_curve": {
            "title": "归一化 H-Q 曲线",
            "x_name": "Q_eq = Q / w (m3/h)",
            "y_name": "H_eq = H / w^2 (m)",
            "scatter_name": f"实际散点 n={len(samples)}",
            "scatter": scatter_points(scatter_df, "Q_eq", "H_eq"),
            "lines": [],
        },
        "efficiency_normalized_curve": {
            "title": "归一化 η-Q 曲线",
            "x_name": "Q_eq = Q / w (m3/h)",
            "y_name": "η",
            "scatter_name": f"实际散点 n={len(samples)}",
            "scatter": scatter_points(scatter_df, "Q_eq", "eta"),
            "lines": [],
        },
    }


def build_chart_data(result, samples) -> Dict[str, Any]:
    q_eq_grid = np.linspace(float(samples["Q_eq"].min()), float(samples["Q_eq"].max()), 120)
    w_curves = representative_speed_ratios(samples["w"])
    theory_lines = query_theory_curves(result.pump_id, result.side, result.group_id)

    a = result.head_coefficients["a"]
    b = result.head_coefficients["b"]
    c = result.head_coefficients["c"]
    j = result.efficiency_coefficients["j"]
    k = result.efficiency_coefficients["k"]
    l = result.efficiency_coefficients["l"]

    head_lines = []
    efficiency_lines = []
    for w_curve in w_curves:
        q_curve = q_eq_grid * w_curve
        head_lines.append(
            {
                "name": f"fit w={w_curve:.2f}",
                "w": float(w_curve),
                "points": line_points(
                    q_curve,
                    (w_curve ** 2) * predict_quadratic([a, b, c], q_eq_grid),
                ),
            }
        )
        efficiency_lines.append(
            {
                "name": f"fit w={w_curve:.2f}",
                "w": float(w_curve),
                "points": line_points(
                    q_curve,
                    predict_quadratic([j, k, l], q_eq_grid),
                ),
            }
        )

    return {
        "head_curve": {
            "title": "H-Q 曲线",
            "x_name": "Q (m3/h)",
            "y_name": "H (m)",
            "scatter_name": f"有效散点 n={result.sample_count}",
            "scatter": scatter_points(samples, "Q", "H"),
            "lines": head_lines,
        },
        "efficiency_curve": {
            "title": "eta-Q 曲线",
            "x_name": "Q (m3/h)",
            "y_name": "eta",
            "scatter_name": f"有效散点 n={result.sample_count}",
            "scatter": scatter_points(samples, "Q", "eta"),
            "lines": efficiency_lines,
        },
        "head_normalized_curve": {
            "title": "归一化 H-Q 曲线",
            "x_name": "Q_eq = Q / w (m3/h)",
            "y_name": "H_eq = H / w^2 (m)",
            "scatter_name": f"归一化散点 n={result.sample_count}",
            "scatter": scatter_points(samples, "Q_eq", "H_eq"),
            "lines": [
                {
                    "name": "实际能效",
                    "points": line_points(q_eq_grid, predict_quadratic([a, b, c], q_eq_grid)),
                }
            ] + theory_lines["head"],
        },
        "efficiency_normalized_curve": {
            "title": "归一化 eta-Q 曲线",
            "x_name": "Q_eq = Q / w (m3/h)",
            "y_name": "eta",
            "scatter_name": f"归一化散点 n={result.sample_count}",
            "scatter": scatter_points(samples, "Q_eq", "eta"),
            "lines": [
                {
                    "name": "实际能效",
                    "points": line_points(q_eq_grid, predict_quadratic([j, k, l], q_eq_grid)),
                }
            ] + theory_lines["efficiency"],
        },
    }


def query_time_range(dataset_name: str = "sample_raw_points") -> Dict[str, Optional[str]]:
    return {
        "min_time": os.getenv("PUMP_DEFAULT_START_TIME"),
        "max_time": os.getenv("PUMP_DEFAULT_END_TIME"),
        "time_count": None,
    }


def source_label(source_type: str) -> str:
    return {
        "header_controller": "冷却侧",
        "chiller": "冷冻侧",
    }.get(source_type, source_type)


def group_display_name(group_id: str, source_type: str) -> str:
    return f"{source_label(source_type)}{group_id}组"


def query_device_options(dataset_name: str = "sample_raw_points") -> Dict[str, Any]:
    catalog = computable_catalog(query_cpn_catalog())
    source_rows = catalog[catalog["cpn_type"].isin([DEVICE_TYPE_CHILLER, DEVICE_TYPE_HEADER])]
    pump_rows = catalog[catalog["cpn_type"] == DEVICE_TYPE_PUMP]

    sources: Dict[str, Dict[str, Any]] = {}
    group_sources: Dict[str, List[str]] = {}
    for _, row in source_rows.iterrows():
        group_id = str(row["group_id"])
        source_type = SOURCE_TYPE_BY_CPN_TYPE.get(int(row["cpn_type"]), "unknown")
        group_sources.setdefault(group_id, [])
        if source_type not in group_sources[group_id]:
            group_sources[group_id].append(source_type)
        sources.setdefault(
            source_type,
            {
                "value": source_type,
                "label": source_label(source_type),
                "devices": [],
            },
        )
        sources[source_type]["devices"].append(
            {
                "id": row["true_cpn_name"],
                "name": row["show_name"],
                "group_id": group_id,
                "cpn_name": row["cpn_name"],
                "cpn_type": int(row["cpn_type"]),
            }
        )

    groups = sorted(catalog["group_id"].dropna().astype(str).unique().tolist())
    pumps = [
        {
            "id": row["true_cpn_name"],
            "name": row["show_name"],
            "group_id": str(row["group_id"]),
            "source_types": group_sources.get(str(row["group_id"]), []),
            "source_label": "、".join(source_label(item) for item in group_sources.get(str(row["group_id"]), [])),
            "cpn_name": row["cpn_name"],
            "cpn_type": int(row["cpn_type"]),
        }
        for _, row in pump_rows.iterrows()
    ]

    return {
        "sources": list(sources.values()),
        "groups": [
            {
                "id": group_id,
                "name": group_display_name(group_id, group_sources.get(group_id, ["unknown"])[0]),
                "source_types": group_sources.get(group_id, []),
                "source_label": "、".join(source_label(item) for item in group_sources.get(group_id, [])),
            }
            for group_id in groups
        ],
        "pumps": pumps,
    }


def source_groups(controller_rows, chiller_rows) -> Dict[str, str]:
    groups: Dict[str, str] = {}
    if not controller_rows.empty:
        for group_id in controller_rows["group_id"].dropna().astype(str).unique().tolist():
            groups[group_id] = "header_controller"
    if not chiller_rows.empty:
        for group_id in chiller_rows["group_id"].dropna().astype(str).unique().tolist():
            groups[group_id] = "chiller"
    return groups


def build_group_payload(
    pump_rows,
    samples,
    results: List[Dict[str, Any]],
    skipped: List[Dict[str, Any]],
    group_sources: Dict[str, str],
) -> List[Dict[str, Any]]:
    result_by_pump = {item["pump_id"]: item for item in results}
    skipped_by_pump = {item["pump_id"]: item for item in skipped}
    sample_counts = samples.groupby("pump_id").size().to_dict() if not samples.empty else {}
    groups: Dict[str, Dict[str, Any]] = {}
    for _, row in pump_rows.drop_duplicates(subset=["group_id", "pump_id"]).iterrows():
        group_id = str(row["group_id"])
        if group_id not in group_sources:
            continue
        pump_id = str(row["pump_id"])
        source_type = group_sources[group_id]
        groups.setdefault(
            group_id,
            {
                "id": group_id,
                "name": group_display_name(group_id, source_type),
                "source_type": source_type,
                "source_label": source_label(source_type),
                "pumps": [],
            },
        )
        groups[group_id]["pumps"].append(
            {
                "id": pump_id,
                "name": row.get("show_name") or row.get("cpn_name") or pump_id,
                "sample_count": int(sample_counts.get(pump_id, 0)),
                "has_result": pump_id in result_by_pump,
                "skipped_reason": skipped_by_pump.get(pump_id, {}).get("reason"),
            }
        )

    for group in groups.values():
        group["pumps"] = sorted(group["pumps"], key=lambda item: item["name"])
    return sorted(groups.values(), key=lambda item: (item["source_type"], item["id"]))


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "chart_mode": "frontend_echarts"}


@app.get("/api/options")
def options(dataset_name: str = "sample_raw_points") -> Dict[str, Any]:
    device_options = query_device_options(dataset_name)
    return {
        "dataset_name": dataset_name,
        "time_range": query_time_range(dataset_name),
        **device_options,
    }


@app.post("/api/regression")
def regression(request: RegressionRequest) -> Dict[str, Any]:
    cfg = config()

    start_time = normalize_datetime(request.start_time)
    end_time = normalize_datetime(request.end_time)
    source_data = real_source_rows(start_time, end_time)
    controller_rows = source_data["controller_rows"]
    chiller_rows = source_data["chiller_rows"]
    pump_rows = source_data["pump_rows"]
    group_sources = source_groups(controller_rows, chiller_rows)
    if not group_sources:
        raise HTTPException(status_code=400, detail="当前时间段内没有干管协调控制器或冷机流量数据")
    if pump_rows.empty:
        raise HTTPException(status_code=400, detail="当前时间段内没有水泵时序数据")

    if request.pump_ids:
        inferred = infer_groups_and_sources_for_pumps(request.pump_ids, controller_rows, chiller_rows, pump_rows)
        source_types = inferred["source_types"]
        group_ids = inferred["group_ids"]
        selected_pump_ids: Optional[List[str]] = request.pump_ids
    else:
        source_types = sorted(set(group_sources.values()))
        group_ids = sorted(group_sources.keys())
        selected_pump_ids = None

    samples, rejects = build_grouped_device_samples(
        cfg,
        controller_rows,
        chiller_rows,
        pump_rows,
        source_types=source_types,
        group_ids=group_ids,
        pump_ids=selected_pump_ids,
        flow_device_ids=None,
    )
    if samples.empty:
        raise HTTPException(status_code=400, detail="当前条件下没有可用于回归的有效样本")

    candidate_pumps = pump_rows[
        pump_rows["group_id"].astype(str).isin(group_ids)
        & (pump_rows["status"].fillna(0) > 0)
    ]["pump_id"].dropna().astype(str).unique().tolist()
    if selected_pump_ids:
        candidate_pumps = [pump_id for pump_id in selected_pump_ids if pump_id in set(candidate_pumps)]
        samples = samples[samples["pump_id"].astype(str).isin(candidate_pumps)].copy()
        if samples.empty:
            raise HTTPException(status_code=400, detail="选中的水泵没有有效样本")

    results = []
    skipped = []
    for pump_id in sorted(candidate_pumps):
        pump_samples = samples[samples["pump_id"].astype(str) == str(pump_id)].copy()
        fit_available = len(pump_samples) >= request.min_samples
        if not fit_available:
            skipped.append({"pump_id": pump_id, "reason": f"only {len(pump_samples)} valid samples"})

        charts = build_scatter_only_chart_data(pump_samples)
        result_payload: Dict[str, Any] = {
            "pump_id": str(pump_id),
            "group_id": str(pump_samples["group_id"].dropna().iloc[0]) if not pump_samples.empty and pump_samples["group_id"].notna().any() else None,
            "side": str(pump_samples["side"].dropna().iloc[0]) if not pump_samples.empty and pump_samples["side"].notna().any() else None,
            "sample_count": int(len(pump_samples)),
            "q_min": float(pump_samples["Q"].min()) if not pump_samples.empty else None,
            "q_max": float(pump_samples["Q"].max()) if not pump_samples.empty else None,
            "w_min": float(pump_samples["w"].min()) if not pump_samples.empty else None,
            "w_max": float(pump_samples["w"].max()) if not pump_samples.empty else None,
            "fit_available": fit_available,
            "fit_reason": None if fit_available else f"only {len(pump_samples)} valid samples",
            "charts": charts,
        }

        if fit_available:
            result, fitted = fit_one_pump(samples, pump_id)
            result_payload.update(
                {
                    "group_id": result.group_id,
                    "side": result.side,
                    "q_min": result.q_min,
                    "q_max": result.q_max,
                    "w_min": result.w_min,
                    "w_max": result.w_max,
                    "head_coefficients": result.head_coefficients,
                    "efficiency_coefficients": result.efficiency_coefficients,
                    "head_metrics": result.head_metrics.__dict__,
                    "efficiency_metrics": result.efficiency_metrics.__dict__,
                    "charts": build_chart_data(result, fitted),
                }
            )

        results.append(result_payload)

    if not results:
        return {
            "request": request.dict(),
            "inferred_group_ids": group_ids,
            "inferred_source_types": source_types,
            "groups": build_group_payload(pump_rows, samples, results, skipped, group_sources),
            "raw_time_count": int(
                len(
                    set(controller_rows.get("sample_time", []))
                    | set(chiller_rows.get("sample_time", []))
                    | set(pump_rows.get("sample_time", []))
                )
            ),
            "valid_sample_count": int(len(samples)),
            "reject_count": int(len(rejects)),
            "sample_counts": samples.groupby("pump_id").size().to_dict(),
            "results": [],
            "skipped": skipped,
        }

    return {
        "request": request.dict(),
        "inferred_group_ids": group_ids,
        "inferred_source_types": source_types,
        "groups": build_group_payload(pump_rows, samples, results, skipped, group_sources),
        "raw_time_count": int(
            len(
                set(controller_rows.get("sample_time", []))
                | set(chiller_rows.get("sample_time", []))
                | set(pump_rows.get("sample_time", []))
            )
        ),
        "valid_sample_count": int(len(samples)),
        "reject_count": int(len(rejects)),
        "sample_counts": samples.groupby("pump_id").size().to_dict(),
        "results": results,
        "skipped": skipped,
    }
