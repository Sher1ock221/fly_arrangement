# 技术栈

## 后端

- Python 3.11
- FastAPI 与 Uvicorn
- SQLAlchemy 2.x 异步 ORM、Alembic 迁移
- PostgreSQL（Compose 服务端模式）与 SQLite（桌面/本地开发模式）
- Pydantic Settings 配置管理
- HTTPX 调用可选的 Ollama 服务和飞书开放平台

## 前端

- Next.js 14 App Router
- React 18、TypeScript 5
- Tailwind CSS
- TanStack React Query 与 TanStack Table
- Radix UI 组件

## 桌面端与部署

- Electron 37 与 electron-builder / NSIS
- PowerShell 启动、运行时准备和桌面集成脚本
- Docker Compose：PostgreSQL、FastAPI、Next.js
- Windows 单机模式使用 SQLite；服务端模式支持 PostgreSQL

## 可选集成

- Ollama：由用户在应用中配置服务地址和模型。
- 飞书：服务端模式的机器人、Webhook 和消息同步；桌面 SQLite 模式不处理飞书公网回调。

版本范围以 `backend/requirements.txt`、`frontend/package.json` 和 `desktop/package.json` 为准。
