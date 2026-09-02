#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Pump curve regression module.

This first version assumes Q, H, w, and eta can be read directly for each pump.
It fits:
  H = a * Q^2 + b * w * Q + c * w^2
  eta = j * (Q / w)^2 + k * (Q / w) + l

Recommended normalized fitting form:
  Q_eq = Q / w
  H_eq = H / w^2
  H_eq = a * Q_eq^2 + b * Q_eq + c
  eta = j * Q_eq^2 + k * Q_eq + l
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    import matplotlib.pyplot as plt
except Exception:  # pragma: no cover - plotting can be disabled in headless installs
    plt = None


COLUMN_ALIASES = {
    "timestamp": ["timestamp", "time", "datetime", "date_time", "DateTime"],
    "pump_id": ["pump_id", "pump", "pump_name", "device", "device_name"],
    "group_id": ["group_id", "group", "pump_group"],
    "side": ["side", "water_side"],
    "status": ["status", "pump_status", "running", "run_status"],
    "Q": ["Q", "q", "flow", "pump_flow", "water_flow"],
    "H": ["H", "h", "head", "pump_head"],
    "w": ["w", "speed_ratio", "ratio", "frequency_ratio"],
    "eta": ["eta", "efficiency", "pump_efficiency"],
}


@dataclass
class CurveMetrics:
    r2: float
    rmse: float


@dataclass
class PumpFitResult:
    pump_id: str
    group_id: Optional[str]
    side: Optional[str]
    sample_count: int
    q_min: float
    q_max: float
    w_min: float
    w_max: float
    head_coefficients: Dict[str, float]
    efficiency_coefficients: Dict[str, float]
    head_metrics: CurveMetrics
    efficiency_metrics: CurveMetrics
    head_formula: str = "H = a * Q^2 + b * w * Q + c * w^2"
    efficiency_formula: str = "eta = j * (Q / w)^2 + k * (Q / w) + l"


def resolve_column(df: pd.DataFrame, canonical: str) -> Optional[str]:
    lower_map = {str(col).lower(): col for col in df.columns}
    for alias in COLUMN_ALIASES[canonical]:
        if alias in df.columns:
            return alias
        if alias.lower() in lower_map:
            return lower_map[alias.lower()]
    return None


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename: Dict[str, str] = {}
    for canonical in COLUMN_ALIASES:
        actual = resolve_column(df, canonical)
        if actual is not None:
            rename[actual] = canonical
    return df.rename(columns=rename)


def read_input(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".csv", ".txt"}:
        return pd.read_csv(path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if suffix == ".json":
        return pd.read_json(path)
    raise ValueError(f"Unsupported input file type: {path.suffix}")


def is_running_status(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce").fillna(0) > 0
    normalized = series.astype(str).str.strip().str.lower()
    return normalized.isin({"1", "true", "yes", "y", "on", "run", "running", "open"})


def clean_samples(df: pd.DataFrame) -> pd.DataFrame:
    df = normalize_columns(df).copy()
    required = ["pump_id", "Q", "H", "w", "eta"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")

    for col in ["Q", "H", "w", "eta"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")

    if "status" in df.columns:
        df = df[is_running_status(df["status"])]

    df = df.dropna(subset=["pump_id", "Q", "H", "w", "eta"])

    # If eta is supplied as percent, normalize it to 0-1.
    eta_median = df["eta"].median() if not df.empty else np.nan
    if pd.notna(eta_median) and eta_median > 1.5:
        df["eta"] = df["eta"] / 100.0

    df = df[(df["Q"] > 0) & (df["H"] > 0) & (df["w"] > 0) & (df["eta"] > 0) & (df["eta"] <= 1)]
    df = df[(df["w"] >= 0.2) & (df["w"] <= 1.2)]
    return df.reset_index(drop=True)


def design_matrix(x: np.ndarray) -> np.ndarray:
    return np.column_stack([x ** 2, x, np.ones_like(x)])


def fit_quadratic(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    beta, *_ = np.linalg.lstsq(design_matrix(x), y, rcond=None)
    return beta


def predict_quadratic(coefficients: Iterable[float], x: np.ndarray) -> np.ndarray:
    beta = np.asarray(list(coefficients), dtype=float)
    return design_matrix(x) @ beta


def metrics(y_true: np.ndarray, y_pred: np.ndarray) -> CurveMetrics:
    residual = y_true - y_pred
    rmse = float(math.sqrt(np.mean(residual ** 2)))
    ss_res = float(np.sum(residual ** 2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return CurveMetrics(r2=float(r2), rmse=rmse)


def fit_one_pump(df: pd.DataFrame, pump_id: str) -> Tuple[PumpFitResult, pd.DataFrame]:
    samples = df[df["pump_id"].astype(str) == str(pump_id)].copy()
    if len(samples) < 10:
        raise ValueError(f"Pump {pump_id} has only {len(samples)} valid samples; at least 10 are recommended.")

    q = samples["Q"].to_numpy(dtype=float)
    h = samples["H"].to_numpy(dtype=float)
    w = samples["w"].to_numpy(dtype=float)
    eta = samples["eta"].to_numpy(dtype=float)

    q_eq = q / w
    h_eq = h / (w ** 2)

    head_beta = fit_quadratic(q_eq, h_eq)  # a, b, c
    eta_beta = fit_quadratic(q_eq, eta)    # j, k, l

    h_pred = (w ** 2) * predict_quadratic(head_beta, q_eq)
    eta_pred = predict_quadratic(eta_beta, q_eq)

    samples["Q_eq"] = q_eq
    samples["H_eq"] = h_eq
    samples["H_pred"] = h_pred
    samples["eta_pred"] = eta_pred

    result = PumpFitResult(
        pump_id=str(pump_id),
        group_id=str(samples["group_id"].dropna().iloc[0]) if "group_id" in samples.columns and samples["group_id"].notna().any() else None,
        side=str(samples["side"].dropna().iloc[0]) if "side" in samples.columns and samples["side"].notna().any() else None,
        sample_count=int(len(samples)),
        q_min=float(np.min(q)),
        q_max=float(np.max(q)),
        w_min=float(np.min(w)),
        w_max=float(np.max(w)),
        head_coefficients={"a": float(head_beta[0]), "b": float(head_beta[1]), "c": float(head_beta[2])},
        efficiency_coefficients={"j": float(eta_beta[0]), "k": float(eta_beta[1]), "l": float(eta_beta[2])},
        head_metrics=metrics(h, h_pred),
        efficiency_metrics=metrics(eta, eta_pred),
    )
    return result, samples


def representative_speed_ratios(w_values: pd.Series) -> List[float]:
    raw = w_values.dropna().astype(float)
    if raw.empty:
        return [1.0]
    candidates = [float(raw.quantile(q)) for q in [0.1, 0.5, 0.9]]
    rounded = []
    for value in candidates:
        value = round(value, 2)
        if value > 0 and value not in rounded:
            rounded.append(value)
    if 1.0 >= raw.min() and 1.0 <= raw.max() and 1.0 not in rounded:
        rounded.append(1.0)
    return sorted(rounded)


def plot_pump_curves(result: PumpFitResult, samples: pd.DataFrame, output_dir: Path) -> Dict[str, str]:
    if plt is None:
        return {}

    output_dir.mkdir(parents=True, exist_ok=True)
    q_eq_grid = np.linspace(float(samples["Q_eq"].min()), float(samples["Q_eq"].max()), 120)
    w_curves = representative_speed_ratios(samples["w"])

    safe_pump_id = str(result.pump_id).replace("/", "_").replace("\\", "_").replace(" ", "_")
    outputs: Dict[str, str] = {}

    sample_label = f"all valid regression samples used by every fit-w line (n={result.sample_count})"

    fig, ax = plt.subplots(figsize=(10, 6))
    scatter = ax.scatter(samples["Q"], samples["H"], c=samples["w"], cmap="viridis", s=44, alpha=0.85, edgecolors="black", linewidths=0.35, label=sample_label, zorder=3)
    for w_curve in w_curves:
        a = result.head_coefficients["a"]
        b = result.head_coefficients["b"]
        c = result.head_coefficients["c"]
        q_curve = q_eq_grid * w_curve
        h_curve = (w_curve ** 2) * predict_quadratic([a, b, c], q_eq_grid)
        ax.plot(q_curve, h_curve, linewidth=2, label=f"fit w={w_curve:.2f}", zorder=2)
    ax.set_title(f"Pump {result.pump_id} H-Q regression | R2={result.head_metrics.r2:.3f}, RMSE={result.head_metrics.rmse:.3f}")
    ax.text(0.02, 0.98, "Each fit-w line uses the same fitted coefficients\nDots = all valid samples, color = speed ratio w", transform=ax.transAxes, va="top", ha="left", fontsize=9, bbox={"boxstyle": "round,pad=0.35", "facecolor": "white", "edgecolor": "#888888", "alpha": 0.86})
    ax.set_xlabel("Q (m3/h)")
    ax.set_ylabel("H (m)")
    ax.grid(True, linestyle="--", alpha=0.35)
    ax.legend()
    fig.colorbar(scatter, ax=ax, label="w")
    head_path = output_dir / f"{safe_pump_id}_head_curve.png"
    fig.tight_layout()
    fig.savefig(head_path, dpi=180)
    plt.close(fig)
    outputs["head_curve_plot"] = str(head_path)

    fig, ax = plt.subplots(figsize=(10, 6))
    scatter = ax.scatter(samples["Q"], samples["eta"], c=samples["w"], cmap="viridis", s=44, alpha=0.85, edgecolors="black", linewidths=0.35, label=sample_label, zorder=3)
    for w_curve in w_curves:
        j = result.efficiency_coefficients["j"]
        k = result.efficiency_coefficients["k"]
        l = result.efficiency_coefficients["l"]
        q_curve = q_eq_grid * w_curve
        eta_curve = predict_quadratic([j, k, l], q_eq_grid)
        ax.plot(q_curve, eta_curve, linewidth=2, label=f"fit w={w_curve:.2f}", zorder=2)
    ax.set_title(f"Pump {result.pump_id} eta-Q regression | R2={result.efficiency_metrics.r2:.3f}, RMSE={result.efficiency_metrics.rmse:.3f}")
    ax.text(0.02, 0.98, "Each fit-w line uses the same fitted coefficients\nDots = all valid samples, color = speed ratio w", transform=ax.transAxes, va="top", ha="left", fontsize=9, bbox={"boxstyle": "round,pad=0.35", "facecolor": "white", "edgecolor": "#888888", "alpha": 0.86})
    ax.set_xlabel("Q (m3/h)")
    ax.set_ylabel("eta")
    ax.set_ylim(bottom=0, top=max(1.0, float(samples["eta"].max()) * 1.1))
    ax.grid(True, linestyle="--", alpha=0.35)
    ax.legend()
    fig.colorbar(scatter, ax=ax, label="w")
    eta_path = output_dir / f"{safe_pump_id}_efficiency_curve.png"
    fig.tight_layout()
    fig.savefig(eta_path, dpi=180)
    plt.close(fig)
    outputs["efficiency_curve_plot"] = str(eta_path)

    fig, ax = plt.subplots(figsize=(10, 6))
    scatter = ax.scatter(samples["Q_eq"], samples["H_eq"], c=samples["w"], cmap="viridis", s=44, alpha=0.85, edgecolors="black", linewidths=0.35, label=f"normalized samples used for head fit (n={result.sample_count})", zorder=3)
    head_eq_curve = predict_quadratic(
        [
            result.head_coefficients["a"],
            result.head_coefficients["b"],
            result.head_coefficients["c"],
        ],
        q_eq_grid,
    )
    ax.plot(q_eq_grid, head_eq_curve, color="#d62728", linewidth=2.4, label="head fit on normalized samples", zorder=2)
    ax.set_title(f"Pump {result.pump_id} normalized head regression | R2={result.head_metrics.r2:.3f}, RMSE={result.head_metrics.rmse:.3f}")
    ax.text(0.02, 0.98, "This is the actual regression view\nQ_eq = Q / w, H_eq = H / w^2", transform=ax.transAxes, va="top", ha="left", fontsize=9, bbox={"boxstyle": "round,pad=0.35", "facecolor": "white", "edgecolor": "#888888", "alpha": 0.86})
    ax.set_xlabel("Q_eq = Q / w (m3/h)")
    ax.set_ylabel("H_eq = H / w^2 (m)")
    ax.grid(True, linestyle="--", alpha=0.35)
    ax.legend()
    fig.colorbar(scatter, ax=ax, label="w")
    head_norm_path = output_dir / f"{safe_pump_id}_head_normalized_curve.png"
    fig.tight_layout()
    fig.savefig(head_norm_path, dpi=180)
    plt.close(fig)
    outputs["head_normalized_curve_plot"] = str(head_norm_path)

    fig, ax = plt.subplots(figsize=(10, 6))
    scatter = ax.scatter(samples["Q_eq"], samples["eta"], c=samples["w"], cmap="viridis", s=44, alpha=0.85, edgecolors="black", linewidths=0.35, label=f"normalized samples used for efficiency fit (n={result.sample_count})", zorder=3)
    eta_curve = predict_quadratic(
        [
            result.efficiency_coefficients["j"],
            result.efficiency_coefficients["k"],
            result.efficiency_coefficients["l"],
        ],
        q_eq_grid,
    )
    ax.plot(q_eq_grid, eta_curve, color="#d62728", linewidth=2.4, label="efficiency fit on normalized samples", zorder=2)
    ax.set_title(f"Pump {result.pump_id} normalized efficiency regression | R2={result.efficiency_metrics.r2:.3f}, RMSE={result.efficiency_metrics.rmse:.3f}")
    ax.text(0.02, 0.98, "This is the actual regression view\nQ_eq = Q / w", transform=ax.transAxes, va="top", ha="left", fontsize=9, bbox={"boxstyle": "round,pad=0.35", "facecolor": "white", "edgecolor": "#888888", "alpha": 0.86})
    ax.set_xlabel("Q_eq = Q / w (m3/h)")
    ax.set_ylabel("eta")
    ax.set_ylim(bottom=0, top=max(1.0, float(samples["eta"].max()) * 1.1))
    ax.grid(True, linestyle="--", alpha=0.35)
    ax.legend()
    fig.colorbar(scatter, ax=ax, label="w")
    eta_norm_path = output_dir / f"{safe_pump_id}_efficiency_normalized_curve.png"
    fig.tight_layout()
    fig.savefig(eta_norm_path, dpi=180)
    plt.close(fig)
    outputs["efficiency_normalized_curve_plot"] = str(eta_norm_path)
    return outputs


def fit_file(input_path: Path, output_dir: Path, pump_ids: Optional[List[str]] = None, min_samples: int = 10) -> Dict[str, object]:
    raw = read_input(input_path)
    clean = clean_samples(raw)
    if clean.empty:
        raise ValueError("No valid pump samples after cleaning.")

    available_pumps = sorted(clean["pump_id"].astype(str).unique().tolist())
    selected = pump_ids or available_pumps

    results = []
    fitted_frames = []
    skipped = []
    for pump_id in selected:
        pump_samples = clean[clean["pump_id"].astype(str) == str(pump_id)]
        if len(pump_samples) < min_samples:
            skipped.append({"pump_id": pump_id, "reason": f"only {len(pump_samples)} valid samples"})
            continue
        result, fitted = fit_one_pump(clean, pump_id)
        plot_paths = plot_pump_curves(result, fitted, output_dir)
        item = asdict(result)
        item["plots"] = plot_paths
        results.append(item)
        fitted_frames.append(fitted)

    output_dir.mkdir(parents=True, exist_ok=True)
    result_payload = {
        "input_file": str(input_path),
        "valid_sample_count": int(len(clean)),
        "available_pumps": available_pumps,
        "results": results,
        "skipped": skipped,
    }
    result_path = output_dir / "pump_curve_fit_results.json"
    result_path.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if fitted_frames:
        fitted_all = pd.concat(fitted_frames, ignore_index=True)
        fitted_all.to_csv(output_dir / "pump_curve_fitted_samples.csv", index=False, encoding="utf-8-sig")

    return result_payload


def create_mysql_tables(mysql_exe: Path, host: str, port: int, user: str, password: str, database: str, schema_path: Path) -> None:
    cmd = [
        str(mysql_exe),
        f"--host={host}",
        f"--port={port}",
        f"--user={user}",
        f"--password={password}",
        f"--database={database}",
    ]
    sql = schema_path.read_text(encoding="utf-8")
    subprocess.run(cmd, input=sql, text=True, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fit pump H-Q and eta-Q regression curves.")
    sub = parser.add_subparsers(dest="command", required=True)

    fit_parser = sub.add_parser("fit", help="Fit pump curves from CSV, Excel, or JSON sample data.")
    fit_parser.add_argument("--input", required=True, type=Path, help="Input file containing pump_id, Q, H, w, eta columns.")
    fit_parser.add_argument("--output-dir", default=Path("output"), type=Path)
    fit_parser.add_argument("--pump-id", action="append", help="Pump id to fit. Repeat to fit multiple. Omit to fit all pumps.")
    fit_parser.add_argument("--min-samples", type=int, default=10)

    db_parser = sub.add_parser("init-db", help="Create MySQL tables from db_schema.mysql.sql.")
    db_parser.add_argument("--mysql-exe", default=Path("mysql"), type=Path)
    db_parser.add_argument("--host", required=True)
    db_parser.add_argument("--port", type=int, default=3306)
    db_parser.add_argument("--user", required=True)
    db_parser.add_argument("--password", required=True)
    db_parser.add_argument("--database", default="pump_curve_model")
    db_parser.add_argument("--schema", default=Path(__file__).with_name("db_schema.mysql.sql"), type=Path)

    args = parser.parse_args()

    if args.command == "fit":
        payload = fit_file(args.input, args.output_dir, args.pump_id, args.min_samples)
        print(json.dumps({
            "output_dir": str(args.output_dir),
            "result_count": len(payload["results"]),
            "skipped": payload["skipped"],
        }, ensure_ascii=False, indent=2))
    elif args.command == "init-db":
        create_mysql_tables(args.mysql_exe, args.host, args.port, args.user, args.password, args.database, args.schema)
        print(f"MySQL tables are ready in database: {args.database}")


if __name__ == "__main__":
    main()
