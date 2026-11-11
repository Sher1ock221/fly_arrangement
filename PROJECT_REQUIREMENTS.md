# 项目范围

## 项目目标

Fly Arrangement 为小型团队提供项目、客户、日程和提醒管理，并支持自然语言 AI 助手。项目既可作为自托管 Web 服务运行，也可在 Windows 上以 Electron + SQLite 单机运行。

## 功能范围

- **项目管理：** 项目资料、负责人、状态与进度、客户关联、协作和治理修复。
- **客户管理：** 客户资料、互动记录、项目关联和合作意向。
- **日历与提醒：** 日程维护、提醒任务、时间语义解析和日程建议。
- **AI 助手：** 连接用户配置的 Ollama 服务，按权限调用项目、客户、日程和提醒工具。
- **账号与审计：** 登录、角色管理、审计记录、系统日志和数据维护。
- **飞书集成：** 服务端模式支持机器人 Webhook 与消息同步；桌面 SQLite 模式不启用公网回调。
- **Windows 桌面端：** Electron 管理本地前后端进程，SQLite 数据存放在应用数据目录。

## 部署模式

| 模式 | 后端 | 数据库 | 外部集成 |
|---|---|---|---|
| 自托管 Web | FastAPI | PostgreSQL | 可配置 Ollama、飞书 |
| Windows 桌面 | FastAPI 本地服务 | SQLite | 可配置本地 Ollama；默认不启用飞书回调 |
| 开发 | FastAPI + Next.js | SQLite 或 PostgreSQL | 按本机环境配置 |

## 安全要求

- 首次使用时通过 `backend/scripts/create_admin.py` 显式创建管理员，不使用通用默认口令。
- 生产环境必须设置至少 32 个字符的 `JWT_SECRET_KEY`。
- 数据库密码、飞书凭据和运行时数据保存在本地环境文件或数据库中，不进入源码仓库。
- 默认 Compose 端口只绑定到本机；需要网络访问时由部署者配置网络边界和 HTTPS。

## 开发环境

- Python 3.11+
- Node.js 20+
- Docker Desktop / Docker Compose（仅 Compose 部署需要）
- Ollama（仅使用本地模型功能时需要）

详细启动步骤见 [README.md](README.md)。
