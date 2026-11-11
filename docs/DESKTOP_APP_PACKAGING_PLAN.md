# Fly Arrangement Windows 桌面版打包改造方案

## 一、改造目标

Fly Arrangement 当前主要面向 Docker Compose 的 Web 部署形态（后端 FastAPI、前端 Next.js、数据库 PostgreSQL）。本方案目标是在不破坏现有部署能力的前提下，新增 Windows 10/11 个人单机桌面版交付路径。

桌面版第一版目标如下：

1. 用户通过 `setup.exe` 安装；
2. 安装后通过桌面图标打开应用；
3. 不要求用户安装 Docker；
4. 不要求用户安装 PostgreSQL；
5. 不注册 Windows 服务；
6. 不做开机自启；
7. 第一版不考虑飞书机器人公网回调能力；
8. 卸载默认保留用户数据；
9. 升级前自动备份本地数据。

## 二、最终运行形态

推荐桌面版运行形态：

- Electron 桌面壳
- 本地 FastAPI 后端
- 本地 Next.js 前端服务
- SQLite 本地数据库
- 使用 Inno Setup 或 electron-builder 生成安装包

推荐启动流程：

1. 用户双击桌面图标；
2. Electron 主进程启动；
3. Electron 检查本地数据目录与基础配置；
4. Electron 拉起本地 FastAPI 后端进程；
5. Electron 拉起或连接本地 Next.js 前端服务；
6. Electron `BrowserWindow` 加载本地前端地址；
7. 应用关闭时尝试停止由 Electron 拉起的本地进程，并做必要的资源回收。

## 三、目录规划

建议桌面版目录规划如下：

- 程序目录：`C:\Program Files\FlyArrangement\`
- 数据目录：`C:\ProgramData\FlyArrangement\`
- SQLite 数据库：`C:\ProgramData\FlyArrangement\data\fly_arrangement.db`
- 日志目录：`C:\ProgramData\FlyArrangement\logs\`
- 备份目录：`C:\ProgramData\FlyArrangement\backups\`
- 配置目录：`C:\ProgramData\FlyArrangement\config\`

说明：

- 程序目录用于安装应用二进制与运行时资源；
- 数据目录用于放置可持久化业务数据，默认在卸载时保留；
- 升级前备份文件写入 `backups` 目录，支持回滚与排障。

## 四、数据库改造原则

数据库改造遵循以下原则：

1. 不删除 PostgreSQL 支持；
2. 新增 SQLite 支持；
3. 后端通过 `DATABASE_URL` 判断当前数据库类型；
4. Docker/服务端模式继续使用 PostgreSQL；
5. 桌面单机模式默认使用 SQLite；
6. SQLite 数据文件统一落在 `ProgramData`；
7. 不建议直接用全部历史 PostgreSQL Alembic 迁移初始化 SQLite；
8. 建议为 SQLite 建立桌面版 baseline schema 或独立初始化路径。

## 五、当前 PostgreSQL 绑定点总结

基于已完成扫描，当前主要 PostgreSQL 绑定点如下：

1. `backend/app/core/config.py` 默认 `DATABASE_URL` 为 PostgreSQL；
2. `backend/app/db/session.py` 使用 `create_async_engine` 创建引擎；
3. `backend/alembic.ini` 默认 `sqlalchemy.url` 为 PostgreSQL；
4. `backend/alembic/env.py` 优先读取环境变量 `DATABASE_URL`；
5. 多个模型使用 PostgreSQL `JSONB`；
6. 部分模型使用 `postgresql_where`；
7. 多个迁移脚本包含 PostgreSQL 专属 SQL/类型；
8. 部分原生 SQL 或脚本需要复核方言兼容性。

## 六、SQLite 兼容改造策略

建议采用“最小改动、分层替换、可回退”的 SQLite 兼容策略：

1. `JSONB` 优先替换为 SQLAlchemy 通用 `JSON` 或 `Text`（按查询需求选择）；
2. `postgresql_where` 采用数据库类型条件分支，或在 SQLite 下移除对应条件索引；
3. `server_default=text("now()")` 统一收敛为可跨库策略（应用层赋值或数据库兼容表达式）；
4. `DateTime(timezone=True)` 明确 SQLite 存储策略（例如统一 UTC 字符串/时间戳）；
5. 原生 SQL 逐段复核，避免依赖 PostgreSQL 专属语法；
6. Alembic 迁移按数据库类型区分执行路径（PostgreSQL 与 SQLite）；
7. 桌面版优先建立 SQLite baseline，不强行重放全部历史 PostgreSQL 迁移。

## 七、前端桌面化策略

前端桌面化建议：

1. `frontend` 为 Next.js 14；
2. 当前阶段不建议强行 `next export`；
3. 第一版 Electron 生产态优先加载本地 Next 服务；
4. 后续若需优化体积与启动速度，再评估静态化路径；
5. 桌面版 `NEXT_PUBLIC_API_BASE_URL` 指向本地 FastAPI 地址（例如 `http://127.0.0.1:<port>`）。

## 八、飞书功能处理策略

飞书相关能力在桌面版第一版处理原则：

1. 第一版桌面单机版不处理飞书公网回调；
2. 可保留现有飞书相关代码和页面；
3. 不主动删除飞书业务代码；
4. 在桌面版文档明确标注：飞书回调能力需要公网服务或内网穿透，单机版默认不可用。

## 九、分阶段实施计划

- **Phase 0：现状扫描（已完成）**  
  已完成后端数据库链路、Alembic、模型类型、原生 SQL、前端运行形态扫描。

- **Phase 1：新增桌面版方案文档（当前阶段）**  
  形成统一改造边界、目标与分步路线，作为后续 Cursor 改造基线。

- **Phase 2：数据库连接层改造（双模式）**  
  建立 PostgreSQL/SQLite 双模式连接能力，桌面默认 SQLite，服务端保持 PostgreSQL。

- **Phase 3：模型层 SQLite 兼容处理**  
  清理或分支化 PostgreSQL 专属字段、索引和默认值策略。

- **Phase 4：SQLite baseline 初始化方案**  
  建立桌面版初始化 schema 路径，避免直接重放整套历史 PG 迁移。

- **Phase 5：后端本地启动脚本**  
  提供桌面版可控启动/停止脚本，统一端口、日志与数据目录注入。

- **Phase 6：Electron 桌面壳**  
  完成主进程、窗口、进程托管与异常退出处理。

- **Phase 7：前端本地服务适配**  
  完成 Next 本地服务启动/连接策略与本地 API 地址配置。

- **Phase 8：安装包、卸载、备份与升级逻辑**  
  接入安装器，落实桌面快捷方式、卸载保留数据、升级前自动备份。

- **Phase 9：验收测试**  
  完成安装、启动、升级、卸载、数据保留、异常恢复与回归验证。

## 十、禁止事项

为控制风险，以下事项在第一版明确禁止：

1. 不要一次性重构全项目；
2. 不要删除 Docker 部署能力；
3. 不要删除 PostgreSQL 支持；
4. 不要删除飞书业务代码；
5. 不要直接全量重写 Alembic 历史迁移；
6. 不要第一版就做自动更新；
7. 不要第一版就做开机自启；
8. 不要第一版就注册 Windows 服务。

## 十一、验收标准

本轮文档验收标准：

1. `docs/DESKTOP_APP_PACKAGING_PLAN.md` 已新增；
2. 文档明确桌面版目标；
3. 文档明确 SQLite 与 PostgreSQL 双模式；
4. 文档明确第一版不处理飞书回调；
5. 文档明确 Electron + FastAPI + Next.js 的本地运行模式；
6. 文档明确后续分阶段改造路径；
7. 除新增该文档外，不修改任何其他文件。

