#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Append dispersed demo time ranges for the pump curve web app.

This script only writes the six current-version tables that store source data:
header controller values, chiller values, and pump device values. It does not
recreate old run/result tables.
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import pandas as pd

from sample_builder import run_mysql, sql_quote


def pump_statuses(index: int, group_no: int, period_index: int = 0) -> Tuple[int, int, int]:
    selector = (index + group_no + period_index) % 16
    if selector in {0, 7}:
        return 1, 1, 0
    if selector == 11:
        return 1, 0, 1
    if selector == 14:
        return 0, 1, 1
    return 1, 1, 1


def controller_status(index: int, group_no: int, offset: int, period_index: int = 0) -> int:
    selector = (index + group_no + period_index) % 10
    if offset == 0 and selector == 6:
        return 0
    if offset == 1 and selector in {0, 5}:
        return 0
    return 1


def chunks(values: List[str], size: int) -> Iterable[List[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def generate_period_rows(
    start: datetime,
    sample_count: int,
    interval_minutes: int,
    period_index: int,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    controller_rows: List[Dict[str, Any]] = []
    chiller_rows: List[Dict[str, Any]] = []
    pump_rows: List[Dict[str, Any]] = []
    denominator = max(sample_count - 1, 1)

    for i in range(sample_count):
        sample_time = (start + timedelta(minutes=interval_minutes * i)).strftime("%Y-%m-%d %H:%M:%S")
        phase = i / denominator
        load_wave = math.sin(i * 0.19 + period_index * 0.85)
        day_bias = 1.0 + 0.035 * period_index

        for group_no in range(1, 4):
            header_group = f"header_group_{group_no}"
            controller_start = (group_no - 1) * 2 + 1
            pump_start = (group_no - 1) * 2 + 1
            pump_indices = [pump_start, pump_start + 1, 6 + group_no]
            group_bias = 1.0 + 0.075 * (group_no - 1)
            header_total = (235 + 455 * phase + 28 * load_wave) * day_bias * group_bias
            controller_split = 0.50 + 0.035 * math.sin(i * 0.17 + group_no + period_index)
            w_base = min(1.04, 0.66 + 0.30 * phase + 0.018 * group_no + 0.018 * period_index)
            speed_delta = 0.030 if (i + group_no + period_index) % 27 == 0 else 0.008
            statuses = pump_statuses(i, group_no, period_index)

            for offset, ratio in enumerate([controller_split, 1 - controller_split]):
                controller_rows.append(
                    {
                        "sample_time": sample_time,
                        "group_id": header_group,
                        "controller_id": f"HCC{controller_start + offset}",
                        "flow_value": round(header_total * ratio, 3),
                        "status": controller_status(i, group_no, offset, period_index),
                    }
                )

            for offset, pump_index in enumerate(pump_indices):
                w = w_base + (offset - 1) * speed_delta
                pump_rows.append(
                    {
                        "sample_time": sample_time,
                        "group_id": header_group,
                        "pump_id": f"CHWP{pump_index}",
                        "status": statuses[offset],
                        "speed_ratio": round(w, 4),
                        "head": round(29.2 + 16.8 * phase + 1.55 * (group_no - 1) + 0.65 * period_index + 0.85 * math.sin(i * 0.16 + offset), 3),
                        "power_kw": round(35.5 + 49 * phase + 3.8 * (group_no - 1) + 1.9 * period_index + 1.3 * math.cos(i * 0.14 + offset), 3),
                    }
                )

        for group_no in range(1, 4):
            chiller_group = f"chiller_group_{group_no}"
            chiller_start = (group_no - 1) * 3 + 1
            pump_start = (group_no - 1) * 2 + 1
            pump_indices = [pump_start, pump_start + 1, 6 + group_no]
            w_base = min(1.04, 0.68 + 0.27 * phase + 0.016 * group_no + 0.015 * period_index)
            speed_delta = 0.032 if (i + group_no + period_index) % 29 == 0 else 0.009
            statuses = pump_statuses(i, group_no, period_index)

            for offset in range(3):
                chiller_index = chiller_start + offset
                status = 1 if offset == 0 or i >= sample_count * offset // 4 else 0
                base_flow = (248 + 190 * phase + 30 * offset + 18 * (group_no - 1)) * day_bias
                chiller_rows.append(
                    {
                        "sample_time": sample_time,
                        "group_id": chiller_group,
                        "chiller_id": f"CH{chiller_index}",
                        "flow_value": round(base_flow + 12 * math.sin(i * 0.23 + offset + period_index), 3),
                        "status": status,
                    }
                )

            for offset, pump_index in enumerate(pump_indices):
                w = w_base + (offset - 1) * speed_delta
                pump_rows.append(
                    {
                        "sample_time": sample_time,
                        "group_id": chiller_group,
                        "pump_id": f"CWP{pump_index}",
                        "status": statuses[offset],
                        "speed_ratio": round(w, 4),
                        "head": round(24.2 + 14.3 * phase + 1.35 * (group_no - 1) + 0.55 * period_index + 0.75 * math.cos(i * 0.18 + offset), 3),
                        "power_kw": round(33.8 + 46 * phase + 3.5 * (group_no - 1) + 1.7 * period_index + 1.2 * math.sin(i * 0.15 + offset), 3),
                    }
                )

    return pd.DataFrame(controller_rows), pd.DataFrame(chiller_rows), pd.DataFrame(pump_rows)


def insert_rows(
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
    statements: List[str] = []

    controller_values = [
        "("
        f"{sql_quote(dataset_name)}, {sql_quote(row['sample_time'])}, {sql_quote(row['group_id'])}, "
        f"{sql_quote(row['controller_id'])}, "
        f"{repr(float(row['flow_value']))}, {int(row['status'])}"
        ")"
        for _, row in controller_rows.iterrows()
    ]
    for batch in chunks(controller_values, 500):
        statements.append(
            """
INSERT INTO pump_header_controller_values
  (dataset_name, sample_time, group_id, controller_id, flow_value, status)
VALUES
"""
            + ",\n".join(batch)
            + """
ON DUPLICATE KEY UPDATE
  group_id = VALUES(group_id),
  flow_value = VALUES(flow_value),
  status = VALUES(status);
"""
        )

    chiller_values = [
        "("
        f"{sql_quote(dataset_name)}, {sql_quote(row['sample_time'])}, {sql_quote(row['group_id'])}, "
        f"{sql_quote(row['chiller_id'])}, {repr(float(row['flow_value']))}, {int(row['status'])}"
        ")"
        for _, row in chiller_rows.iterrows()
    ]
    for batch in chunks(chiller_values, 500):
        statements.append(
            """
INSERT INTO pump_chiller_values
  (dataset_name, sample_time, group_id, chiller_id, flow_value, status)
VALUES
"""
            + ",\n".join(batch)
            + """
ON DUPLICATE KEY UPDATE
  group_id = VALUES(group_id),
  flow_value = VALUES(flow_value),
  status = VALUES(status);
"""
        )

    pump_values = [
        "("
        f"{sql_quote(dataset_name)}, {sql_quote(row['sample_time'])}, {sql_quote(row['group_id'])}, "
        f"{sql_quote(row['pump_id'])}, {int(row['status'])}, {repr(float(row['speed_ratio']))}, "
        f"{repr(float(row['head']))}, {repr(float(row['power_kw']))}"
        ")"
        for _, row in pump_rows.iterrows()
    ]
    for batch in chunks(pump_values, 500):
        statements.append(
            """
INSERT INTO pump_device_values
  (dataset_name, sample_time, group_id, pump_id, status, speed_ratio, head, power_kw)
VALUES
"""
            + ",\n".join(batch)
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Append dispersed demo pump curve data to MySQL.")
    parser.add_argument("--mysql-exe", default=r"G:\mysql-8.0.46-winx64\bin\mysql.exe")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default="wdlwdl123.")
    parser.add_argument("--database", default="pump_curve_model")
    parser.add_argument("--dataset-name", default="sample_raw_points")
    args = parser.parse_args()

    periods = [
        (datetime(2026, 8, 7, 8, 0, 0), 50, 10),
        (datetime(2026, 8, 15, 9, 30, 0), 50, 12),
        (datetime(2026, 8, 24, 13, 0, 0), 50, 15),
        (datetime(2026, 9, 1, 6, 0, 0), 50, 20),
    ]
    total = {"controller_row_count": 0, "chiller_row_count": 0, "pump_row_count": 0}
    for period_index, (start, sample_count, interval_minutes) in enumerate(periods, start=1):
        controller_rows, chiller_rows, pump_rows = generate_period_rows(start, sample_count, interval_minutes, period_index)
        counts = insert_rows(
            Path(args.mysql_exe),
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
        for key, value in counts.items():
            total[key] += value
        print(f"{start:%Y-%m-%d}: {counts}")

    print(f"total: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
