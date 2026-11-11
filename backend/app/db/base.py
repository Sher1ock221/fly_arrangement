"""
数据库 Base 统一入口，供 Alembic 等使用。
"""
from app.models.base import Base

__all__ = ["Base"]
