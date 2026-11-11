-- =============================================================================
-- Fly Arrangement 数据库结构升级脚本
-- 用途：为 AI Agent 提供更稳定的数据操作与索引，保持现有表结构兼容
-- 执行前请备份数据库。建议在维护窗口执行。
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 第一步：升级 customers 表（先执行，因 projects 将引用 customers）
-- -----------------------------------------------------------------------------
ALTER TABLE customers
  ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_customers_company ON customers(company);

-- -----------------------------------------------------------------------------
-- 第二步：升级 projects 表
-- -----------------------------------------------------------------------------
-- 2.1 新增字段
ALTER TABLE projects
  ADD COLUMN IF NOT EXISTS customer_id INTEGER NULL,
  ADD COLUMN IF NOT EXISTS status VARCHAR(50) NULL,
  ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now();

-- 2.2 为空 project_no 按 id 顺序自动生成 P001, P002, P003...
UPDATE projects
SET project_no = 'P' || LPAD(id::text, 3, '0')
WHERE project_no IS NULL OR trim(project_no) = '';

-- 2.3 将 project_no 改为 NOT NULL 并限制为 VARCHAR(20)
--     （若已有 UNIQUE 约束则保留，仅改类型与非空）
ALTER TABLE projects
  ALTER COLUMN project_no SET NOT NULL,
  ALTER COLUMN project_no TYPE VARCHAR(20) USING project_no::VARCHAR(20);

-- 2.4 可选：为 customer_id 添加外键（若需严格关联可取消注释）
-- ALTER TABLE projects
--   ADD CONSTRAINT fk_projects_customer
--   FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE SET NULL;

-- 2.5 索引
CREATE INDEX IF NOT EXISTS idx_projects_customer_id ON projects(customer_id);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);

-- -----------------------------------------------------------------------------
-- 第三步：升级 audit_logs 表
-- -----------------------------------------------------------------------------
ALTER TABLE audit_logs
  ADD COLUMN IF NOT EXISTS operator VARCHAR(100) NULL;

ALTER TABLE audit_logs
  ALTER COLUMN timestamp SET DEFAULT now();

-- -----------------------------------------------------------------------------
-- 第四步：升级 chat_records 表
-- -----------------------------------------------------------------------------
ALTER TABLE chat_records
  ADD COLUMN IF NOT EXISTS session_id VARCHAR(100) NULL,
  ADD COLUMN IF NOT EXISTS intent VARCHAR(100) NULL;

CREATE INDEX IF NOT EXISTS idx_chat_records_session ON chat_records(session_id);

-- -----------------------------------------------------------------------------
-- 第五步：升级 system_logs 表
-- -----------------------------------------------------------------------------
ALTER TABLE system_logs
  ADD COLUMN IF NOT EXISTS request_id VARCHAR(100) NULL;

CREATE INDEX IF NOT EXISTS idx_system_logs_request_id ON system_logs(request_id);

-- -----------------------------------------------------------------------------
-- 第六步：升级 ai_configs 表
-- -----------------------------------------------------------------------------
ALTER TABLE ai_configs
  ADD COLUMN IF NOT EXISTS temperature FLOAT NOT NULL DEFAULT 0.2,
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now();

COMMIT;

-- =============================================================================
-- 说明：
-- 1. 使用 IF NOT EXISTS / IF NOT EXISTS 避免重复执行报错。
-- 2. projects.project_no 空值已按 id 补全，不会破坏已有数据。
-- 3. customer_name 保留，customer_id 为新增关联字段，可后续由应用同步维护。
-- 4. 外键 fk_projects_customer 默认未启用，避免历史数据中无效 customer_id 导致约束失败。
-- =============================================================================
