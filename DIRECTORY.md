# 目录说明

```text
Fly_arrangement/
├── backend/
│   ├── app/
│   │   ├── agent/          # AI 工具和任务技能
│   │   ├── api/            # FastAPI 路由
│   │   ├── core/           # 应用配置与安全
│   │   ├── db/             # 数据库连接、URL 与 SQLite 支持
│   │   ├── models/         # SQLAlchemy 数据模型
│   │   ├── schemas/        # API 数据结构
│   │   └── services/       # 业务逻辑
│   ├── alembic/            # PostgreSQL 数据库迁移
│   ├── scripts/            # SQLite 初始化、管理员创建、桌面启动
│   └── tests/              # 后端安全与管理员初始化测试
├── frontend/
│   ├── src/app/            # Next.js 页面和路由
│   ├── src/components/     # 页面组件
│   ├── src/contexts/        # 登录与聊天状态
│   ├── src/lib/             # API、日期和前端工具
│   └── src/types/           # TypeScript 类型
├── desktop/                 # Electron 主进程、配置与图标资源
├── packaging/scripts/       # 桌面版 Python / Node 运行时准备
├── docs/                    # 桌面构建和安装说明
├── backend/docs/            # 飞书服务端接入检查清单
├── docker-compose.yml       # PostgreSQL + backend + frontend
├── .env.example             # Docker Compose 本地配置模板
├── PROJECT_REQUIREMENTS.md  # 当前项目范围
├── TECH_STACK.md            # 技术栈
└── README.md                # 功能介绍与启动说明
```

本地 `.env`、数据库、日志、依赖目录、运行时和安装包属于生成或运行数据，不纳入仓库。桌面图标位于 `desktop/build/`，属于打包源资源，应保留。
