#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Seed local InfluxDB demo time-series data for pump curve regression.

The script reads device names and groups from MySQL ly_czwxc.ly_cpn, then writes
InfluxDB line protocol using the measurement names expected by the web backend.
It uses only the standard library for InfluxDB writes so it can run even when
influxdb-client is not installed in the current Python environment.
"""

from __future__ import annotations

import argparse
import math
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
from zoneinfo import ZoneInfo


DEVICE_TYPE_CHILLER = 32
DEVICE_TYPE_PUMP = 36
DEVICE_TYPE_HEADER = 38

POINTS = {
    "status": "0x00000200",
    "pump_speed_ratio": "0x00000210",
    "pump_head": "0x00000212",
    "pump_power": "0x00000220",
    "chiller_flow": "0x0000021D",
    "header_flow": "0x0000024A",
}


def mysql_cmd(args: argparse.Namespace, database: str | None = None) -> List[str]:
    cmd = [
        str(Path(args.mysql_exe)),
        f"--host={args.mysql_host}",
        f"--port={args.mysql_port}",
        f"--user={args.mysql_user}",
        f"--password={args.mysql_password}",
        "--default-character-set=utf8mb4",
        "--batch",
        "--raw",
    ]
    if database:
        cmd.append(f"--database={database}")
    return cmd


def run_mysql(args: argparse.Namespace, sql: str, database: str | None = None) -> str:
    proc = subprocess.run(
        mysql_cmd(args, database),
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


def parse_rows(output: str) -> List[Dict[str, str]]:
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) < 2:
        return []
    headers = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        values = line.split("\t")
        rows.append({header: values[index] if index < len(values) else "" for index, header in enumerate(headers)})
    return rows


def read_catalog(args: argparse.Namespace) -> List[Dict[str, str]]:
    sql = f"""
SELECT
  CAST(cpn_type AS CHAR) AS cpn_type,
  CAST(group_id AS CHAR) AS group_id,
  show_name,
  true_cpn_name
FROM `{args.mysql_table}`
WHERE cpn_type IN ({DEVICE_TYPE_CHILLER}, {DEVICE_TYPE_PUMP}, {DEVICE_TYPE_HEADER})
  AND group_id IS NOT NULL
  AND true_cpn_name IS NOT NULL
  AND true_cpn_name <> ''
ORDER BY group_id, cpn_type, true_cpn_name;
"""
    rows = parse_rows(run_mysql(args, sql, args.mysql_database))
    seen = set()
    unique_rows = []
    for row in rows:
        key = (row["cpn_type"], row["group_id"], row["true_cpn_name"])
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)
    return unique_rows


def measurement(cpn_type: int, point_name: str) -> str:
    return f"ly_{cpn_type:02d}_FFFFFFFF_{point_name}"


def lp_escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace(" ", "\\ ").replace(",", "\\,").replace("=", "\\=")


def line(meas: str, cpn_name: str, value: float, ts_ns: int) -> str:
    return f"{lp_escape(meas)},cpn_name={lp_escape(cpn_name)} value={float(value):.6f} {ts_ns}"


def local_timestamp_ns(dt: datetime, tz: ZoneInfo) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return int(dt.astimezone(ZoneInfo("UTC")).timestamp() * 1_000_000_000)


def group_catalog(rows: Iterable[Dict[str, str]]) -> Dict[str, Dict[int, List[str]]]:
    groups: Dict[str, Dict[int, List[str]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        groups[str(row["group_id"])][int(float(row["cpn_type"]))].append(str(row["true_cpn_name"]))
    return groups


def running_pattern(index: int, group_index: int, device_index: int, minimum_running: bool = True) -> int:
    if not minimum_running and (index + group_index + device_index) % 9 == 0:
        return 0
    if (index + group_index + device_index) % 17 in {0, 11}:
        return 0
    return 1


def pump_statuses(count: int, index: int, group_index: int) -> List[int]:
    statuses = [running_pattern(index, group_index, i) for i in range(count)]
    if not any(statuses):
        statuses[index % count] = 1
    return statuses


def source_statuses(count: int, index: int, group_index: int) -> List[int]:
    statuses = [running_pattern(index, group_index, i, minimum_running=False) for i in range(count)]
    if count and not any(statuses):
        statuses[0] = 1
    return statuses


def pump_values(group_index: int, pump_index: int, sample_index: int, phase: float, status: int) -> Tuple[float, float, float]:
    if not status:
        return 0.0, 0.0, 0.0
    base_w = 0.70 + 0.22 * phase + 0.006 * math.sin(sample_index * 0.27 + group_index)
    w = max(0.55, min(1.02, base_w + 0.003 * pump_index))
    head = 21.0 + 3.2 * group_index + 13.5 * phase + 0.45 * pump_index + 0.7 * math.sin(sample_index * 0.19 + pump_index)
    power = 28.0 + 5.5 * group_index + 42.0 * phase + 1.8 * pump_index + 1.2 * math.cos(sample_index * 0.23)
    return w, head, power


def source_flow(group_index: int, device_index: int, sample_index: int, phase: float, status: int, cpn_type: int) -> float:
    if not status:
        return 0.0
    base = 80.0 if cpn_type == DEVICE_TYPE_CHILLER else 170.0
    scale = 85.0 if cpn_type == DEVICE_TYPE_CHILLER else 120.0
    return base + scale * phase + 12.0 * group_index + 8.0 * device_index + 5.5 * math.sin(sample_index * 0.31 + device_index)


def build_lines(catalog: List[Dict[str, str]], args: argparse.Namespace) -> List[str]:
    groups = group_catalog(catalog)
    tz = ZoneInfo(args.timezone)
    starts = [
        datetime.fromisoformat(args.start_one),
        datetime.fromisoformat(args.start_two),
        datetime.fromisoformat(args.start_three),
    ]
    all_lines: List[str] = []

    for period_index, start in enumerate(starts):
        for sample_index in range(args.samples_per_period):
            phase = sample_index / max(args.samples_per_period - 1, 1)
            dt = start + timedelta(minutes=args.interval_minutes * sample_index)
            ts_ns = local_timestamp_ns(dt, tz)

            for group_order, group_id in enumerate(sorted(groups.keys(), key=lambda item: (len(item), item))):
                group = groups[group_id]
                group_index = group_order + period_index + 1

                pumps = sorted(group.get(DEVICE_TYPE_PUMP, []))
                pump_runs = pump_statuses(len(pumps), sample_index, group_index) if pumps else []
                for pump_index, pump_name in enumerate(pumps):
                    status = pump_runs[pump_index]
                    w, head, power = pump_values(group_index, pump_index, sample_index, phase, status)
                    all_lines.append(line(measurement(DEVICE_TYPE_PUMP, POINTS["status"]), pump_name, status, ts_ns))
                    all_lines.append(line(measurement(DEVICE_TYPE_PUMP, POINTS["pump_speed_ratio"]), pump_name, w, ts_ns))
                    all_lines.append(line(measurement(DEVICE_TYPE_PUMP, POINTS["pump_head"]), pump_name, head, ts_ns))
                    all_lines.append(line(measurement(DEVICE_TYPE_PUMP, POINTS["pump_power"]), pump_name, power, ts_ns))

                for cpn_type, flow_point in [
                    (DEVICE_TYPE_CHILLER, POINTS["chiller_flow"]),
                    (DEVICE_TYPE_HEADER, POINTS["header_flow"]),
                ]:
                    devices = sorted(group.get(cpn_type, []))
                    source_runs = source_statuses(len(devices), sample_index, group_index)
                    for device_index, device_name in enumerate(devices):
                        status = source_runs[device_index] if source_runs else 0
                        flow = source_flow(group_index, device_index, sample_index, phase, status, cpn_type)
                        all_lines.append(line(measurement(cpn_type, POINTS["status"]), device_name, status, ts_ns))
                        all_lines.append(line(measurement(cpn_type, flow_point), device_name, flow, ts_ns))

    return all_lines


def write_influx(args: argparse.Namespace, lines: List[str]) -> None:
    params = urllib.parse.urlencode({"org": args.influx_org, "bucket": args.influx_bucket, "precision": "ns"})
    url = f"{args.influx_url.rstrip('/')}/api/v2/write?{params}"
    request = urllib.request.Request(
        url,
        data=("\n".join(lines) + "\n").encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Token {args.influx_token}",
            "Content-Type": "text/plain; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status not in {204, 200}:
                raise RuntimeError(f"Unexpected InfluxDB status: {response.status}")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot connect to InfluxDB at {args.influx_url}: {exc}") from exc
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"InfluxDB write failed: HTTP {exc.code}: {detail}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed demo pump/chiller/header controller values into InfluxDB.")
    parser.add_argument("--mysql-exe", default=r"G:\mysql-8.0.46-winx64\bin\mysql.exe")
    parser.add_argument("--mysql-host", default="127.0.0.1")
    parser.add_argument("--mysql-port", type=int, default=3306)
    parser.add_argument("--mysql-user", default="root")
    parser.add_argument("--mysql-password", default="wdlwdl123.")
    parser.add_argument("--mysql-database", default="ly_czwxc")
    parser.add_argument("--mysql-table", default="ly_cpn")
    parser.add_argument("--influx-url", default="http://127.0.0.1:8086")
    parser.add_argument("--influx-token", default="aeALbvY_ikDyDa0s1UiljrkavEAjToUUznM82-CZFnYWGV2XdrlynZL8vYLM8pFEoOyFyS-Fndshb8vSuZ_zxg==")
    parser.add_argument("--influx-org", default="lynkros")
    parser.add_argument("--influx-bucket", default="czwxc_1")
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--samples-per-period", type=int, default=72)
    parser.add_argument("--interval-minutes", type=int, default=20)
    parser.add_argument("--start-one", default="2026-08-01T00:00:00")
    parser.add_argument("--start-two", default="2026-08-07T00:00:00")
    parser.add_argument("--start-three", default="2026-08-20T00:00:00")
    args = parser.parse_args()

    catalog = read_catalog(args)
    if not catalog:
        raise RuntimeError(f"No devices found in {args.mysql_database}.{args.mysql_table}.")
    lines = build_lines(catalog, args)
    write_influx(args, lines)
    print(f"Wrote {len(lines)} InfluxDB points for {len(catalog)} catalog devices.")
    print(f"Bucket: {args.influx_bucket}, org: {args.influx_org}, URL: {args.influx_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
