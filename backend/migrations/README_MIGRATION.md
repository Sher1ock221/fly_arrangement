# 数据库结构升级说明

本文档说明如何执行 `migrations/upgrade_db_structure.sql`，以及升级前后差异与注意事项。

## 一、升级内容概览

| 表名 | 变更类型 | 主要内容 |
|------|----------|----------|
| **customers** | 新增列、索引 | `is_deleted`、`created_at`；索引 `idx_customers_company` |
| **projects** | 新增列、列约束、索引、数据回填 | `customer_id`、`status`、`is_deleted`、`created_at`；`project_no` 改为 NOT NULL + VARCHAR(20)，空值按 id 生成 P001/P002/…；索引 `idx_projects_customer_id`、`idx_projects_status` |
| **audit_logs** | 新增列、默认值 | `operator`；`timestamp` 默认值 `now()` |
| **chat_records** | 新增列、索引 | `session_id`、`intent`；索引 `idx_chat_records_session` |
| **system_logs** | 新增列、索引 | `request_id`；索引 `idx_system_logs_request_id` |
| **ai_configs** | 新增列 | `temperature`、`created_at` |

- 所有新增列均使用 `IF NOT EXISTS`，索引使用 `IF NOT EXISTS`，**可重复执行**，不会破坏已有数据。
- `projects.project_no` 在脚本中会先对空值按 `id` 生成 P001、P002…，再改为 NOT NULL，保证无脏数据。

## 二、执行前准备

1. **备份数据库**（必须）  
   - 使用 `pg_dump` 或运维备份工具做全量备份后再执行升级。

2. **确认数据库类型**  
   - 脚本针对 **PostgreSQL**（含 `TIMESTAMPTZ`、`JSONB`、`now()` 等），其他数据库需改写。

3. **建议在低峰或维护窗口执行**  
   - 部分 `ALTER TABLE` 会短暂锁表，大表时可能阻塞写入。

## 三、执行方式

### 方式一：psql 命令行

```bash
psql -h <host> -U <user> -d <database> -f backend/migrations/upgrade_db_structure.sql
```

### 方式二：Docker 内执行（当前项目常用）

```bash
docker compose exec db psql -U postgres -d <数据库名> -f /path/in/container/upgrade_db_structure.sql
```

若脚本已挂载到容器内，例如在项目根目录执行：

```bash
docker compose exec -T db psql -U postgres -d fly_arrangement < backend/migrations/upgrade_db_structure.sql
```

（具体数据库名以 `docker-compose.yml` 或环境变量为准。）

### 方式三：在 DBeaver / pgAdmin 等工具中

打开 `upgrade_db_structure.sql`，选中全部内容执行即可。确保在一个事务中执行（脚本已包含 `BEGIN;` 与 `COMMIT;`）。

## 四、执行后校验

1. **表结构**  
   - 在 PostgreSQL 中查看各表列与索引，例如：  
     `\d projects`、`\d customers`、`\d audit_logs` 等。

2. **projects.project_no**  
   - 确认无 NULL：  
     `SELECT id, project_no FROM projects WHERE project_no IS NULL;`  
     应为 0 行。

3. **应用启动**  
   - 启动后端服务，确认无 ORM 报错（如缺失列、类型不匹配）。  
   - 若使用 Alembic，可再做一次 `alembic stamp` 或新增一条迁移记录，与当前结构一致（可选）。

## 五、与 ORM 的对应关系

- 后端 **SQLAlchemy 模型**（`app/models/`）已按上述结构更新，字段类型、索引、默认值与本脚本一致。
- 执行顺序建议：**先跑完本 SQL 升级脚本，再部署新版本后端**，避免旧代码访问新列时出现兼容问题；若先部署代码再执行脚本，需保证新列可空或有默认值（当前脚本已满足）。

## 六、回滚说明

- 本脚本**未提供自动回滚**。回滚需依赖备份恢复或自行编写反向 `ALTER TABLE` / `DROP INDEX`。
- 若仅执行了部分语句即失败，可在排查后修复数据，再次执行整个脚本（依赖 `IF NOT EXISTS` 可重复执行）。

## 七、外键说明

- 脚本中 **未启用** `projects.customer_id` 到 `customers.id` 的外键约束，以避免历史数据中存在无效 `customer_id` 导致约束失败。
- 若你已清理历史数据并希望强制引用完整性，可在脚本中取消注释“第二步”里的外键相关语句后再执行。

---

**总结**：备份后执行 `upgrade_db_structure.sql`，执行完毕检查表结构与 `project_no` 无 NULL，再部署新后端即可完成本次数据库结构升级。
