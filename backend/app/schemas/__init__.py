"""Pydantic schemas package.

说明：
为避免循环依赖与启动阶段脆弱性，本包的 __init__.py 不做任何顶层聚合导入。
请在需要的地方按模块显式 import（例如：`from app.schemas.project import ProjectRead`）。
"""

__all__: list[str] = []
