import unittest
from unittest.mock import patch

import pandas as pd

from pump_curve_web.backend.main import (
    InfluxSettings,
    RegressionRequest,
    _aggregate_window_delta,
    _align_influx_points,
    pivot_device_values,
    regression,
)


class InfluxTimeAlignmentTests(unittest.TestCase):
    def test_misaligned_pump_points_are_joined_in_same_window(self):
        status = "ly_24_FFFFFFFF_00000200"
        ratio = "ly_24_FFFFFFFF_00000201"
        head = "ly_24_FFFFFFFF_00000212"
        power = "ly_24_FFFFFFFF_00000220"
        frame = pd.DataFrame(
            [
                {
                    "sample_time": "2026-09-07T01:50:49Z",
                    "device_id": "B301-CWP",
                    "measurement": status,
                    "value": 1,
                },
                {
                    "sample_time": "2026-09-07T01:50:49Z",
                    "device_id": "B301-CWP",
                    "measurement": ratio,
                    "value": 0.8,
                },
                {
                    "sample_time": "2026-09-07T01:51:37Z",
                    "device_id": "B301-CWP",
                    "measurement": head,
                    "value": 15.715,
                },
                {
                    "sample_time": "2026-09-07T01:51:37Z",
                    "device_id": "B301-CWP",
                    "measurement": power,
                    "value": 52.554,
                },
                {
                    "sample_time": "2026-09-07T01:54:50Z",
                    "device_id": "B301-CWP",
                    "measurement": ratio,
                    "value": 0.799,
                },
            ]
        )
        settings = InfluxSettings(aggregate_window="5m", timezone="Asia/Shanghai")

        aligned = _align_influx_points(frame, settings)
        aligned["group_id"] = "1"
        aligned["show_name"] = "B301-CWP"
        aligned["cpn_name"] = "B301-CWP"
        pivot = pivot_device_values(
            aligned,
            {
                status: "status",
                ratio: "w",
                head: "H",
                power: "power",
            },
        )

        self.assertEqual(len(pivot), 1)
        self.assertEqual(pivot.iloc[0]["sample_time"], "2026-09-07 09:50:00")
        self.assertEqual(pivot.iloc[0]["status"], 1)
        self.assertAlmostEqual(pivot.iloc[0]["w"], 0.799)
        self.assertAlmostEqual(pivot.iloc[0]["H"], 15.715)
        self.assertAlmostEqual(pivot.iloc[0]["power"], 52.554)

    def test_combined_flux_duration_is_supported(self):
        self.assertEqual(_aggregate_window_delta("1h30m"), pd.Timedelta(minutes=90))
        self.assertIsNone(_aggregate_window_delta("off"))

    @patch("pump_curve_web.backend.main.build_grouped_device_samples")
    @patch("pump_curve_web.backend.main.real_source_rows")
    @patch("pump_curve_web.backend.main.config", return_value={})
    def test_regression_returns_stopped_pumps_as_unfitted(
        self,
        _mock_config,
        mock_real_source_rows,
        mock_build_samples,
    ):
        controller_rows = pd.DataFrame(
            [
                {
                    "sample_time": "2026-09-07 09:50:00",
                    "group_id": "1",
                    "device_id": "B301-CHW",
                    "flow_value": 1000,
                }
            ]
        )
        pump_rows = pd.DataFrame(
            [
                {
                    "sample_time": "2026-09-07 09:50:00",
                    "group_id": "1",
                    "pump_id": f"B30{number}-CWP",
                    "show_name": f"{number}号冷却泵",
                    "cpn_name": f"B30{number}-CWP",
                    "status": 1 if number in {1, 4} else 0,
                    "w": 0.8 if number in {1, 4} else 0,
                    "H": 15 if number in {1, 4} else 0,
                    "power": 50 if number in {1, 4} else 0,
                }
                for number in range(1, 5)
            ]
        )
        empty_chillers = pd.DataFrame(
            columns=["sample_time", "group_id", "device_id", "status", "flow_value"]
        )
        mock_real_source_rows.return_value = {
            "catalog": pd.DataFrame(),
            "controller_rows": controller_rows,
            "chiller_rows": empty_chillers,
            "pump_rows": pump_rows,
        }
        mock_build_samples.return_value = (
            pd.DataFrame(
                [
                    {
                        "pump_id": pump_id,
                        "group_id": "1",
                        "side": "header_controller",
                        "Q": 500,
                        "H": 15,
                        "w": 0.8,
                        "eta": 0.4,
                    }
                    for pump_id in ["B301-CWP", "B304-CWP"]
                ]
            ),
            pd.DataFrame(),
        )

        result = regression(
            RegressionRequest(
                start_time="2026-09-07 09:50:00",
                end_time="2026-09-07 10:00:00",
                min_samples=10,
            )
        )

        by_pump = {item["pump_id"]: item for item in result["results"]}
        self.assertEqual(set(by_pump), {"B301-CWP", "B302-CWP", "B303-CWP", "B304-CWP"})
        self.assertEqual(by_pump["B302-CWP"]["sample_count"], 0)
        self.assertFalse(by_pump["B302-CWP"]["fit_available"])
        self.assertEqual(
            by_pump["B302-CWP"]["fit_reason"],
            "no running records in selected time range",
        )
        self.assertEqual(by_pump["B302-CWP"]["group_id"], "1")


if __name__ == "__main__":
    unittest.main()
