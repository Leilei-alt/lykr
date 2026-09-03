#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Seed normalized pump theory curves for the current grouped-device demo data.

The frontend already draws dashed theory lines when the backend returns rows
from pump_theory_curve_sets / pump_theory_curve_points. This script rebuilds
those theory rows so their pump_id, group_id, and side match the latest
header-controller/chiller grouping workflow.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List

import numpy as np

from pump_curve_regression import fit_one_pump, predict_quadratic
from sample_builder import (
    build_grouped_device_samples,
    read_chiller_rows_from_db,
    read_config,
    read_controller_rows_from_db,
    read_pump_rows_from_db,
    run_mysql,
    sql_quote,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "pump_model_config" / "pump_model_config.template.json"


def sql_float(value: float) -> str:
    number = float(value)
    if not np.isfinite(number):
        return "NULL"
    return f"{number:.10g}"


def batched(items: List[str], size: int) -> Iterable[List[str]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def ensure_theory_schema(mysql_exe: Path, host: str, port: int, user: str, password: str, database: str) -> None:
    run_mysql(
        mysql_exe,
        host,
        port,
        user,
        password,
        """
ALTER TABLE pump_theory_curve_sets
  MODIFY side VARCHAR(128) NOT NULL DEFAULT 'unknown';
""",
        database,
    )


def seed_theory_curves(
    mysql_exe: Path,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    dataset_name: str,
    point_count: int,
    curve_name: str,
) -> int:
    cfg = read_config(CONFIG_PATH)
    controller_rows = read_controller_rows_from_db(mysql_exe, host, port, user, password, database, dataset_name)
    chiller_rows = read_chiller_rows_from_db(mysql_exe, host, port, user, password, database, dataset_name)
    pump_rows = read_pump_rows_from_db(mysql_exe, host, port, user, password, database, dataset_name)
    samples, _rejects = build_grouped_device_samples(cfg, controller_rows, chiller_rows, pump_rows)
    if samples.empty:
        raise RuntimeError(f"No valid samples found for dataset {dataset_name!r}.")

    ensure_theory_schema(mysql_exe, host, port, user, password, database)

    seeded = 0
    for pump_id in sorted(samples["pump_id"].dropna().astype(str).unique().tolist()):
        result, fitted = fit_one_pump(samples, pump_id)
        q_eq_min = float(fitted["Q_eq"].min())
        q_eq_max = float(fitted["Q_eq"].max())
        if q_eq_min == q_eq_max:
            continue

        q_eq_grid = np.linspace(q_eq_min, q_eq_max, point_count)
        head = predict_quadratic(
            [
                result.head_coefficients["a"],
                result.head_coefficients["b"],
                result.head_coefficients["c"],
            ],
            q_eq_grid,
        )
        eta = predict_quadratic(
            [
                result.efficiency_coefficients["j"],
                result.efficiency_coefficients["k"],
                result.efficiency_coefficients["l"],
            ],
            q_eq_grid,
        )

        # Keep the demo theory curve close to measured behavior so both are readable.
        theory_head = np.maximum(head * 1.012, 0.0)
        theory_eta = np.clip(eta * 1.01 + 0.003, 0.05, 0.95)

        insert_set_sql = f"""
INSERT INTO pump_theory_curve_sets
  (curve_name, pump_id, group_id, side, source_type, speed_ratio, is_normalized, active, remark)
VALUES
  ({sql_quote(curve_name)}, {sql_quote(result.pump_id)}, {sql_quote(result.group_id)}, {sql_quote(result.side)}, 'sample_design_data', 1.0, 1, 1, 'Generated from current grouped-device sample data')
ON DUPLICATE KEY UPDATE
  group_id = VALUES(group_id),
  source_type = VALUES(source_type),
  speed_ratio = VALUES(speed_ratio),
  is_normalized = VALUES(is_normalized),
  active = VALUES(active),
  remark = VALUES(remark);
"""
        run_mysql(mysql_exe, host, port, user, password, insert_set_sql, database)

        delete_points_sql = f"""
DELETE p
FROM pump_theory_curve_points AS p
JOIN pump_theory_curve_sets AS s ON s.id = p.curve_set_id
WHERE s.curve_name = {sql_quote(curve_name)}
  AND s.pump_id = {sql_quote(result.pump_id)}
  AND s.side = {sql_quote(result.side)};
"""
        run_mysql(mysql_exe, host, port, user, password, delete_points_sql, database)

        values = []
        for index, (q_eq, h_eq, eta_value) in enumerate(zip(q_eq_grid, theory_head, theory_eta)):
            values.append(
                "("
                f"(SELECT id FROM pump_theory_curve_sets "
                f"WHERE curve_name = {sql_quote(curve_name)} "
                f"AND pump_id = {sql_quote(result.pump_id)} "
                f"AND side = {sql_quote(result.side)} LIMIT 1), "
                f"{index}, {sql_float(q_eq)}, {sql_float(h_eq)}, {sql_float(eta_value)}, "
                f"1.0, {sql_float(q_eq)}, {sql_float(h_eq)}"
                ")"
            )

        for chunk in batched(values, 200):
            insert_points_sql = """
INSERT INTO pump_theory_curve_points
  (curve_set_id, point_index, q, h, eta, w, q_eq, h_eq)
VALUES
""" + ",\n".join(chunk) + """
ON DUPLICATE KEY UPDATE
  q = VALUES(q),
  h = VALUES(h),
  eta = VALUES(eta),
  w = VALUES(w),
  q_eq = VALUES(q_eq),
  h_eq = VALUES(h_eq);
"""
            run_mysql(mysql_exe, host, port, user, password, insert_points_sql, database)

        seeded += 1

    return seeded


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed current pump theory curves into MySQL.")
    parser.add_argument("--mysql-exe", default=r"G:\mysql-8.0.46-winx64\bin\mysql.exe")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default="wdlwdl123.")
    parser.add_argument("--database", default="pump_curve_model")
    parser.add_argument("--dataset-name", default="sample_raw_points")
    parser.add_argument("--point-count", type=int, default=25)
    parser.add_argument("--curve-name", default="theory")
    args = parser.parse_args()

    count = seed_theory_curves(
        Path(args.mysql_exe),
        args.host,
        args.port,
        args.user,
        args.password,
        args.database,
        args.dataset_name,
        args.point_count,
        args.curve_name,
    )
    print(f"Seeded {count} theory curve sets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
