USE pump_curve_model;

CREATE TABLE IF NOT EXISTS pump_point_index (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  device_type VARCHAR(64) NOT NULL COMMENT 'Device type, such as pump/header_controller/chiller',
  point_name VARCHAR(191) NOT NULL COMMENT 'Point variable name, such as 0x00000200',
  point_role VARCHAR(64) NOT NULL COMMENT 'Business role, such as pump_status',
  target_table VARCHAR(128) NOT NULL COMMENT 'Business table that stores the value',
  target_column VARCHAR(128) NOT NULL COMMENT 'Column in target_table that stores the value',
  unit VARCHAR(32) NULL,
  data_type VARCHAR(32) NOT NULL DEFAULT 'DOUBLE',
  description VARCHAR(512) NULL,
  active TINYINT NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_pump_point_index_device_point (device_type, point_name),
  KEY idx_pump_point_index_role (point_role),
  KEY idx_pump_point_index_target (target_table, target_column),
  KEY idx_pump_point_index_active (active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO pump_point_index
  (device_type, point_name, point_role, target_table, target_column, unit, data_type, description, active)
VALUES
  ('pump', '0x00000200', 'pump_status', 'pump_device_values', 'status', 'bool', 'TINYINT', 'Pump running status: 1 means running, 0 means stopped.', 1),
  ('pump', '0x00000210', 'pump_speed_ratio', 'pump_device_values', 'speed_ratio', NULL, 'DOUBLE', 'Pump speed ratio w.', 1),
  ('pump', '0x00000212', 'pump_head', 'pump_device_values', 'head', 'm', 'DOUBLE', 'Pump head H.', 1),
  ('pump', '0x00000220', 'pump_power', 'pump_device_values', 'power_kw', 'kW', 'DOUBLE', 'Pump current electric power P.', 1),
  ('chiller', '0x00000200', 'chiller_status', 'pump_chiller_values', 'status', 'bool', 'TINYINT', 'Chiller running status: 1 means running, 0 means stopped.', 1),
  ('chiller', '0x0000021D', 'chiller_flow', 'pump_chiller_values', 'flow_value', 'm3/h', 'DOUBLE', 'Chiller flow Q.', 1),
  ('header_controller', '0x00000200', 'header_controller_status', 'pump_header_controller_values', 'status', 'bool', 'TINYINT', 'Header controller running status: 1 means running, 0 means stopped.', 1),
  ('header_controller', '0x0000024A', 'header_controller_flow', 'pump_header_controller_values', 'flow_value', 'm3/h', 'DOUBLE', 'Header controller water flow Q.', 1)
ON DUPLICATE KEY UPDATE
  point_role = VALUES(point_role),
  target_table = VALUES(target_table),
  target_column = VALUES(target_column),
  unit = VALUES(unit),
  data_type = VALUES(data_type),
  description = VALUES(description),
  active = VALUES(active);
