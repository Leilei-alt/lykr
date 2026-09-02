#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
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
    build_samples,
    read_config,
    read_raw_points_from_db,
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


class RegressionRequest(BaseModel):
    dataset_name: str = "sample_raw_points"
    start_time: str
    end_time: str
    side: str
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


def mysql_settings() -> MysqlSettings:
    return MysqlSettings()


def config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise HTTPException(status_code=500, detail=f"配置文件不存在: {CONFIG_PATH}")
    return read_config(CONFIG_PATH)


def query_time_range(dataset_name: str = "sample_raw_points") -> Dict[str, Optional[str]]:
    settings = mysql_settings()
    sql = f"""
SELECT
  DATE_FORMAT(MIN(sample_time), '%Y-%m-%dT%H:%i') AS min_time,
  DATE_FORMAT(MAX(sample_time), '%Y-%m-%dT%H:%i') AS max_time,
  COUNT(DISTINCT sample_time) AS time_count
FROM pump_raw_point_values
WHERE dataset_name = {sql_quote(dataset_name)};
"""
    output = run_mysql(
        Path(settings.mysql_exe),
        settings.host,
        settings.port,
        settings.user,
        settings.password,
        sql,
        settings.database,
    )
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) < 2:
        return {"min_time": None, "max_time": None, "time_count": 0}
    parts = lines[-1].split("\t")
    return {
        "min_time": None if parts[0] == "NULL" else parts[0],
        "max_time": None if parts[1] == "NULL" else parts[1],
        "time_count": int(parts[2]) if len(parts) > 2 and parts[2] != "NULL" else 0,
    }


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


def build_chart_data(result, samples) -> Dict[str, Any]:
    q_eq_grid = np.linspace(float(samples["Q_eq"].min()), float(samples["Q_eq"].max()), 120)
    w_curves = representative_speed_ratios(samples["w"])

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
                    "name": "normalized fit",
                    "points": line_points(q_eq_grid, predict_quadratic([a, b, c], q_eq_grid)),
                }
            ],
        },
        "efficiency_normalized_curve": {
            "title": "归一化 eta-Q 曲线",
            "x_name": "Q_eq = Q / w (m3/h)",
            "y_name": "eta",
            "scatter_name": f"归一化散点 n={result.sample_count}",
            "scatter": scatter_points(samples, "Q_eq", "eta"),
            "lines": [
                {
                    "name": "normalized fit",
                    "points": line_points(q_eq_grid, predict_quadratic([j, k, l], q_eq_grid)),
                }
            ],
        },
    }


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "chart_mode": "frontend_echarts"}


@app.get("/api/options")
def options(dataset_name: str = "sample_raw_points") -> Dict[str, Any]:
    cfg = config()
    groups = []
    for group in cfg.get("pump_groups", []):
        groups.append(
            {
                "id": group.get("id"),
                "name": group.get("name"),
                "side": group.get("side"),
                "description": group.get("description"),
                "facilities": [
                    {
                        "id": facility.get("id"),
                        "name": facility.get("name"),
                        "status_point": facility.get("status"),
                        "flow_point": facility.get("flow"),
                    }
                    for facility in group.get("facilities", [])
                ],
                "pumps": [
                    {
                        "id": pump.get("id"),
                        "name": pump.get("name"),
                        "status_point": pump.get("status"),
                        "frequency_point": pump.get("frequency"),
                        "power_point": pump.get("power"),
                        "head_point": pump.get("head"),
                    }
                    for pump in group.get("pumps", [])
                ],
                "flow_source": group.get("flow_source"),
                "allocation": group.get("allocation"),
            }
        )
    return {
        "dataset_name": dataset_name,
        "time_range": query_time_range(dataset_name),
        "groups": groups,
    }


@app.post("/api/regression")
def regression(request: RegressionRequest) -> Dict[str, Any]:
    if request.side not in {"chilled_water", "cooling_water"}:
        raise HTTPException(status_code=400, detail="side 只能是 chilled_water 或 cooling_water")
    if not request.facility_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个冷机/冷却设备")
    if not request.pump_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个水泵")

    cfg = config()
    groups = side_groups(cfg, request.side)
    selected_group_config = filtered_config_for_request(cfg, request)

    settings = mysql_settings()
    raw = read_raw_points_from_db(
        Path(settings.mysql_exe),
        settings.host,
        settings.port,
        settings.user,
        settings.password,
        settings.database,
        request.dataset_name,
        normalize_datetime(request.start_time),
        normalize_datetime(request.end_time),
    )
    apply_ui_status_selection(raw, groups, request.facility_ids, request.pump_ids)
    samples, rejects = build_samples(selected_group_config, raw)
    if samples.empty:
        raise HTTPException(status_code=400, detail="当前条件下没有可用于回归的有效样本")

    samples = samples[samples["pump_id"].astype(str).isin(request.pump_ids)].copy()
    if samples.empty:
        raise HTTPException(status_code=400, detail="选中的水泵没有有效样本")

    results = []
    skipped = []
    for pump_id in request.pump_ids:
        pump_samples = samples[samples["pump_id"].astype(str) == str(pump_id)]
        if len(pump_samples) < request.min_samples:
            skipped.append({"pump_id": pump_id, "reason": f"only {len(pump_samples)} valid samples"})
            continue
        result, fitted = fit_one_pump(samples, pump_id)
        results.append(
            {
                "pump_id": result.pump_id,
                "group_id": result.group_id,
                "side": result.side,
                "sample_count": result.sample_count,
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

    if not results:
        raise HTTPException(status_code=400, detail="有效样本数量不足，无法完成回归")

    return {
        "request": request.dict(),
        "raw_time_count": int(len(raw)),
        "valid_sample_count": int(len(samples)),
        "reject_count": int(len(rejects)),
        "sample_counts": samples.groupby("pump_id").size().to_dict(),
        "results": results,
        "skipped": skipped,
    }
