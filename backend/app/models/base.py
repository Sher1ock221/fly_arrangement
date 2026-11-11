"""
所有模型的基类与 MetaData，用于 Alembic 等。
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """ORM 声明式基类。"""

    pass
