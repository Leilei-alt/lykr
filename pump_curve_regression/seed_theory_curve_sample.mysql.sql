USE pump_curve_model;

INSERT INTO pump_theory_curve_sets
  (curve_name, pump_id, group_id, side, source_type, speed_ratio, is_normalized, active, remark)
VALUES
  ('理论', 'CHWP1', 'chw_group_1', 'chilled_water', 'sample_design_data', 1.0, 1, 1, 'Sample normalized theory curve close to current actual regression data'),
  ('理论', 'CHWP2', 'chw_group_1', 'chilled_water', 'sample_design_data', 1.0, 1, 1, 'Sample normalized theory curve close to current actual regression data'),
  ('理论', 'CWP1', 'cw_group_1', 'cooling_water', 'sample_design_data', 1.0, 1, 1, 'Sample normalized theory curve close to current actual regression data'),
  ('理论', 'CWP2', 'cw_group_1', 'cooling_water', 'sample_design_data', 1.0, 1, 1, 'Sample normalized theory curve close to current actual regression data')
ON DUPLICATE KEY UPDATE
  group_id = VALUES(group_id),
  source_type = VALUES(source_type),
  speed_ratio = VALUES(speed_ratio),
  is_normalized = VALUES(is_normalized),
  active = VALUES(active),
  remark = VALUES(remark);

INSERT INTO pump_theory_curve_points
  (curve_set_id, point_index, q, h, eta, w, q_eq, h_eq)
WITH RECURSIVE seq AS (
  SELECT 0 AS point_index
  UNION ALL
  SELECT point_index + 1 FROM seq WHERE point_index < 24
),
curve_input AS (
  SELECT
    s.id AS curve_set_id,
    s.pump_id,
    seq.point_index,
    CASE
      WHEN s.pump_id IN ('CHWP1', 'CHWP2') THEN 154.17 + seq.point_index * ((334.185 - 154.17) / 24.0)
      ELSE 173.895 + seq.point_index * ((436.32 - 173.895) / 24.0)
    END AS q_eq
  FROM pump_theory_curve_sets AS s
  JOIN seq
  WHERE s.curve_name = '理论'
    AND s.pump_id IN ('CHWP1', 'CHWP2', 'CWP1', 'CWP2')
),
curve_values AS (
  SELECT
    curve_set_id,
    point_index,
    q_eq,
    CASE
      WHEN pump_id = 'CHWP1' THEN 1.015 * (0.0001527159182716838 * POW(q_eq, 2) - 0.19905733562281436 * q_eq + 89.52252779609653)
      WHEN pump_id = 'CHWP2' THEN 1.015 * (0.00025053508089160616 * POW(q_eq, 2) - 0.24766483309927195 * q_eq + 97.3298695882483)
      WHEN pump_id = 'CWP1' THEN 1.015 * (0.00001583195012775713 * POW(q_eq, 2) - 0.053866878075144085 * q_eq + 53.67104236077371)
      ELSE 1.015 * (-0.000019357183225529527 * POW(q_eq, 2) - 0.032246224568763894 * q_eq + 51.97263271213355)
    END AS h_eq,
    CASE
      WHEN pump_id = 'CHWP1' THEN LEAST(0.95, GREATEST(0.05, 1.015 * (0.0000018367274637029161 * POW(q_eq, 2) + 0.0008306538745468577 * q_eq + 0.10512109831232086) + 0.004))
      WHEN pump_id = 'CHWP2' THEN LEAST(0.95, GREATEST(0.05, 1.015 * (0.000002126585148768941 * POW(q_eq, 2) + 0.0006050214031542589 * q_eq + 0.1324234556131368) + 0.004))
      WHEN pump_id = 'CWP1' THEN LEAST(0.95, GREATEST(0.05, 1.015 * (-0.0000003586189490622509 * POW(q_eq, 2) + 0.0016192490616256964 * q_eq - 0.022363195254922225) + 0.004))
      ELSE LEAST(0.95, GREATEST(0.05, 1.015 * (0.00000029178460221534987 * POW(q_eq, 2) + 0.0012077449151295355 * q_eq + 0.02658078443789336) + 0.004))
    END AS eta
  FROM curve_input
)
SELECT
  curve_set_id,
  point_index,
  ROUND(q_eq, 3) AS q,
  ROUND(h_eq, 3) AS h,
  ROUND(eta, 5) AS eta,
  1.0 AS w,
  ROUND(q_eq, 3) AS q_eq,
  ROUND(h_eq, 3) AS h_eq
FROM curve_values
ON DUPLICATE KEY UPDATE
  q = VALUES(q),
  h = VALUES(h),
  eta = VALUES(eta),
  w = VALUES(w),
  q_eq = VALUES(q_eq),
  h_eq = VALUES(h_eq);
