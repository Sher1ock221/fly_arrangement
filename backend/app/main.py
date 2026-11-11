"""
FastAPI 应用入口 - 项目管理与客户管理系统后端
路由挂载在 /api/v1 下；启动时连接数据库并启动应用，表结构由 Alembic 管理。
"""
from contextlib import asynccontextmanager
import asyncio
import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from app.api import ai, auth, admin, admin_project_governance, calendar, chat, customers, health, logs, maintenance, projects, reminders
from app.db.session import AsyncSessionLocal
from app.db.desktop_mode import is_desktop_sqlite_backend
from app.models import SystemLog


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时连接数据库，初始化默认管理员（若无）。"""
    from datetime import datetime, timezone
    import logging as _log
    app.state.start_time = datetime.now(timezone.utc)
    desk_sqlite = is_desktop_sqlite_backend()
    app.state.desktop_sqlite = desk_sqlite
    if desk_sqlite:
        try:
            async with AsyncSessionLocal() as db:
                from app.services.project_owner_repair_queue_runtime import (
                    ensure_project_owner_repair_queue_table,
                )

                await ensure_project_owner_repair_queue_table(db)
                await db.commit()
        except Exception as e:
            _log.getLogger("app.main").warning(
                "desktop_sqlite: ensure_project_owner_repair_queue_table failed: %s", e
            )

    async def _run_feishu_history_sync_once() -> None:
        """启动后延迟执行飞书私聊离线补偿（仅一次），不阻塞 API 启动。"""
        _log.getLogger("app.main").info("startup feishu history sync scheduled")
        await asyncio.sleep(5)
        _log.getLogger("app.main").info("startup feishu history sync started")
        try:
            async with AsyncSessionLocal() as db:
                from app.services.feishu_history_sync_service import run_feishu_history_sync_once
                await run_feishu_history_sync_once(db)
                await db.commit()
        except Exception as e:
            _log.getLogger("app.main").exception(
                "feishu history sync failed: %s", e, exc_info=True
            )

    if not desk_sqlite:
        asyncio.create_task(_run_feishu_history_sync_once())
    else:
        _log.getLogger("app.main").info("desktop_sqlite_mode: skip feishu history sync startup task")

    async def _run_ollama_warmup() -> None:
        """启动后延迟执行 Ollama 预热，不阻塞 API。"""
        _log.getLogger("app.main").info("startup ollama warmup scheduled")
        await asyncio.sleep(2)
        try:
            async with AsyncSessionLocal() as db:
                from app.services.ollama_service import run_warmup
                await run_warmup(db)
        except Exception as e:
            _log.getLogger("app.main").exception("ollama warmup failed: %s", e)

    if not desk_sqlite:
        asyncio.create_task(_run_ollama_warmup())
    else:
        _log.getLogger("app.main").info("desktop_sqlite_mode: skip ollama warmup startup task")

    async def _run_replay_pending_feishu_messages() -> None:
        """AI 就绪后重放离线补偿中因 AI 未就绪而 pending 的消息。延迟 15s 后执行，每 30s 重试一轮，共 3 轮。"""
        _log.getLogger("app.main").info("feishu replay pending scheduled (after 15s, then every 30s x3)")
        await asyncio.sleep(15)
        for round_num in range(3):
            try:
                async with AsyncSessionLocal() as db:
                    from app.services.feishu_history_sync_service import replay_pending_feishu_messages
                    n = await replay_pending_feishu_messages(db)
                    await db.commit()
                _log.getLogger("app.main").info("feishu replay pending round %s replayed %s messages", round_num + 1, n)
            except Exception as e:
                _log.getLogger("app.main").exception("feishu replay pending failed: %s", e, exc_info=True)
            if round_num < 2:
                await asyncio.sleep(30)
        _log.getLogger("app.main").info("feishu replay pending finished")

    if not desk_sqlite:
        asyncio.create_task(_run_replay_pending_feishu_messages())
    else:
        _log.getLogger("app.main").info("desktop_sqlite_mode: skip feishu replay pending startup task")

    async def _reminder_scheduler_loop() -> None:
        """每分钟检查到期提醒并通过飞书发送。"""
        _log.getLogger("app.main").info("reminder scheduler started (60s interval)")
        while True:
            await asyncio.sleep(60)
            try:
                async with AsyncSessionLocal() as db:
                    from app.services.reminder_service import process_due_reminders

                    n = await process_due_reminders(db)
                    await db.commit()
                    if n:
                        _log.getLogger("app.main").info("reminder tick processed %s task(s)", n)
            except Exception as e:
                _log.getLogger("app.main").exception("reminder tick failed: %s", e, exc_info=True)

    asyncio.create_task(_reminder_scheduler_loop())
    yield


app = FastAPI(
    title="Fly Arrangement API",
    version="0.1.0",
    description="项目管理 + 客户管理 + AI 助手",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """全局异常处理器：捕获未处理异常并写入 SystemLog。"""
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                SystemLog(
                    level="ERROR",
                    module=f"{exc.__class__.__module__}.{exc.__class__.__name__}",
                    message=str(exc) or "Unhandled exception",
                    stack_trace="".join(
                        traceback.format_exception(type(exc), exc, exc.__traceback__)
                    )[:8000],
                )
            )
            await db.flush()
            await db.commit()
    except Exception:
        # 若数据库不可用，避免异常处理器再次抛错导致循环
        pass
    return JSONResponse(status_code=500, content={"detail": "内部服务器错误"})


@app.get("/")
async def root():
    """根路径"""
    return {"status": "ok"}


# 健康检查（由 app.api.health 提供 /health）
app.include_router(health.router)
app.include_router(auth.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(admin_project_governance.router, prefix="/api/v1")
app.include_router(maintenance.router, prefix="/api/v1/admin")
app.include_router(projects.router, prefix="/api/v1")
app.include_router(customers.router, prefix="/api/v1")
app.include_router(calendar.router, prefix="/api/v1")
app.include_router(reminders.router, prefix="/api/v1")
app.include_router(ai.router, prefix="/api/v1")
if not is_desktop_sqlite_backend():
    # 延迟导入：桌面 SQLite 启动时不加载飞书 API 模块及其依赖链
    from app.api import admin_feishu, ai_feishu, auth_feishu

    app.include_router(ai_feishu.router, prefix="/api/v1")
    app.include_router(admin_feishu.router, prefix="/api/v1")
    app.include_router(auth_feishu.router, prefix="/api/v1")
app.include_router(logs.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
