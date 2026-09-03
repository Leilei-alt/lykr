CREATE DATABASE IF NOT EXISTS pump_curve_model
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE pump_curve_model;

CREATE TABLE IF NOT EXISTS pump_model_variables (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  point_name VARCHAR(191) NOT NULL,
  role VARCHAR(64) NOT NULL,
  group_id VARCHAR(128) NULL,
  side ENUM('chilled_water', 'cooling_water', 'unknown') NOT NULL DEFAULT 'unknown',
  device_id VARCHAR(128) NULL,
  device_type ENUM('pump', 'facility', 'group', 'unknown') NOT NULL DEFAULT 'unknown',
  unit VARCHAR(32) NULL,
  description VARCHAR(512) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_pump_model_variables_point_role_group_device (point_name, role, group_id, device_id),
  KEY idx_pump_model_variables_point (point_name),
  KEY idx_pump_model_variables_group (group_id, side)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

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

CREATE TABLE IF NOT EXISTS pump_raw_point_values (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  dataset_name VARCHAR(128) NOT NULL,
  sample_time DATETIME NOT NULL,
  point_name VARCHAR(191) NOT NULL,
  numeric_value DOUBLE NULL,
  text_value VARCHAR(255) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_pump_raw_point_values_dataset_time_point (dataset_name, sample_time, point_name),
  KEY idx_pump_raw_point_values_time (sample_time),
  KEY idx_pump_raw_point_values_point_time (point_name, sample_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS pump_header_controller_values (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  dataset_name VARCHAR(128) NOT NULL,
  sample_time DATETIME NOT NULL,
  group_id VARCHAR(128) NOT NULL COMMENT 'Unique group number shared by controllers and pumps',
  controller_id VARCHAR(128) NOT NULL,
  flow_point_name VARCHAR(191) NOT NULL DEFAULT '0x0000024A',
  flow_value DOUBLE NOT NULL COMMENT 'Header controller flow Q, m3/h',
  status TINYINT NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_header_controller_dataset_time_device (dataset_name, sample_time, controller_id),
  KEY idx_header_controller_dataset_time_group (dataset_name, sample_time, group_id),
  KEY idx_header_controller_group_time (group_id, sample_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS pump_chiller_values (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  dataset_name VARCHAR(128) NOT NULL,
  sample_time DATETIME NOT NULL,
  group_id VARCHAR(128) NOT NULL COMMENT 'Unique group number shared by chillers and pumps',
  chiller_id VARCHAR(128) NOT NULL,
  flow_value DOUBLE NOT NULL COMMENT 'Chiller flow Q, m3/h',
  status TINYINT NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_chiller_dataset_time_device (dataset_name, sample_time, chiller_id),
  KEY idx_chiller_dataset_time_group (dataset_name, sample_time, group_id),
  KEY idx_chiller_group_time (group_id, sample_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS pump_device_values (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  dataset_name VARCHAR(128) NOT NULL,
  sample_time DATETIME NOT NULL,
  group_id VARCHAR(128) NOT NULL COMMENT 'Unique group number for this pump',
  pump_id VARCHAR(128) NOT NULL,
  status TINYINT NOT NULL COMMENT '1 means running',
  speed_ratio DOUBLE NOT NULL COMMENT 'Direct speed ratio w, 0-1',
  head DOUBLE NOT NULL COMMENT 'Pump head H, m',
  power_kw DOUBLE NOT NULL COMMENT 'Pump input power, kW',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_pump_device_dataset_time_pump (dataset_name, sample_time, pump_id),
  KEY idx_pump_device_dataset_time_group (dataset_name, sample_time, group_id),
  KEY idx_pump_device_pump_time (pump_id, sample_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS pump_curve_runs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  run_name VARCHAR(128) NOT NULL,
  source_file VARCHAR(512) NULL,
  config_file VARCHAR(512) NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'created',
  filters_json JSON NULL,
  note TEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_pump_curve_runs_created_at (created_at),
  KEY idx_pump_curve_runs_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS pump_curve_samples (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  run_id BIGINT UNSIGNED NULL,
  sample_time DATETIME NULL,
  group_id VARCHAR(128) NULL,
  side ENUM('chilled_water', 'cooling_water', 'unknown') NOT NULL DEFAULT 'unknown',
  pump_id VARCHAR(128) NOT NULL,
  pump_status TINYINT NULL,
  facility_running_count INT NULL,
  pump_running_count INT NULL,
  q_total DOUBLE NULL COMMENT 'Group total flow, m3/h',
  q DOUBLE NOT NULL COMMENT 'Single pump flow, m3/h',
  h DOUBLE NOT NULL COMMENT 'Pump head, m',
  power_kw DOUBLE NULL COMMENT 'Pump input power, kW',
  frequency_hz DOUBLE NULL COMMENT 'Pump frequency, Hz',
  speed_ratio DOUBLE NOT NULL COMMENT 'w = frequency / rated_frequency',
  eta DOUBLE NOT NULL COMMENT 'Pump efficiency, 0-1',
  q_eq DOUBLE NULL COMMENT 'Q / w',
  h_eq DOUBLE NULL COMMENT 'H / w^2',
  h_pred DOUBLE NULL,
  eta_pred DOUBLE NULL,
  source_json JSON NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_pump_curve_samples_run_pump (run_id, pump_id),
  KEY idx_pump_curve_samples_pump_time (pump_id, sample_time),
  KEY idx_pump_curve_samples_group_side (group_id, side),
  CONSTRAINT fk_pump_curve_samples_run
    FOREIGN KEY (run_id) REFERENCES pump_curve_runs(id)
    ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS pump_curve_fit_results (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  run_id BIGINT UNSIGNED NULL,
  pump_id VARCHAR(128) NOT NULL,
  group_id VARCHAR(128) NULL,
  side ENUM('chilled_water', 'cooling_water', 'unknown') NOT NULL DEFAULT 'unknown',
  model_type ENUM('head_curve', 'efficiency_curve') NOT NULL,
  formula VARCHAR(256) NOT NULL,
  coefficients_json JSON NOT NULL,
  sample_count INT NOT NULL,
  q_min DOUBLE NULL,
  q_max DOUBLE NULL,
  w_min DOUBLE NULL,
  w_max DOUBLE NULL,
  r2 DOUBLE NULL,
  rmse DOUBLE NULL,
  plot_path VARCHAR(512) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_pump_curve_fit_result (run_id, pump_id, model_type),
  KEY idx_pump_curve_fit_results_pump (pump_id),
  CONSTRAINT fk_pump_curve_fit_results_run
    FOREIGN KEY (run_id) REFERENCES pump_curve_runs(id)
    ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS pump_curve_points (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  fit_result_id BIGINT UNSIGNED NOT NULL,
  speed_ratio DOUBLE NOT NULL,
  q DOUBLE NOT NULL,
  predicted_value DOUBLE NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_pump_curve_points_result_w_q (fit_result_id, speed_ratio, q),
  CONSTRAINT fk_pump_curve_points_result
    FOREIGN KEY (fit_result_id) REFERENCES pump_curve_fit_results(id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS pump_theory_curve_sets (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  curve_name VARCHAR(128) NOT NULL COMMENT 'Theory curve display name',
  pump_id VARCHAR(128) NOT NULL,
  group_id VARCHAR(128) NULL,
  side VARCHAR(128) NOT NULL DEFAULT 'unknown',
  source_type VARCHAR(128) NULL COMMENT 'Manufacturer, design, manual input, etc.',
  speed_ratio DOUBLE NOT NULL DEFAULT 1.0 COMMENT 'w for the source theory curve',
  is_normalized TINYINT(1) NOT NULL DEFAULT 1,
  active TINYINT(1) NOT NULL DEFAULT 1,
  remark VARCHAR(512) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_pump_theory_curve_sets_name_pump (curve_name, pump_id, side),
  KEY idx_pump_theory_curve_sets_pump_side (pump_id, side, active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS pump_theory_curve_points (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  curve_set_id BIGINT UNSIGNED NOT NULL,
  point_index INT NOT NULL,
  q DOUBLE NULL COMMENT 'Source theory flow, m3/h',
  h DOUBLE NULL COMMENT 'Source theory head, m',
  eta DOUBLE NULL COMMENT 'Source theory efficiency, 0-1',
  w DOUBLE NOT NULL DEFAULT 1.0,
  q_eq DOUBLE NOT NULL COMMENT 'Normalized flow, Q / w',
  h_eq DOUBLE NULL COMMENT 'Normalized head, H / w^2',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_pump_theory_curve_points_set_index (curve_set_id, point_index),
  KEY idx_pump_theory_curve_points_set_qeq (curve_set_id, q_eq),
  CONSTRAINT fk_pump_theory_curve_points_set
    FOREIGN KEY (curve_set_id) REFERENCES pump_theory_curve_sets(id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
