# Windows 桌面版

桌面版使用 Electron 启动本地 FastAPI 后端与 Next.js 前端。开发态数据位于项目根目录的 `desktop-data-electron/`；安装版数据位于 `C:\ProgramData\FlyArrangement\`。两种模式均使用 SQLite，服务绑定到本机回环地址。

## 开发启动

需要 Windows、Python 3.11 和 Node.js 20。先从项目根目录准备运行时并构建前端：

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\scripts\prepare_backend_runtime.ps1
powershell -ExecutionPolicy Bypass -File .\packaging\scripts\prepare_node_runtime.ps1
cd frontend
npm ci
npm run build
```

然后启动 Electron：

```powershell
cd ..\desktop
npm ci
npm start
```

本地地址为前端 `http://127.0.0.1:13000`、后端健康检查 `http://127.0.0.1:18000/health`。

## 创建首个管理员

应用不会预置通用管理员口令。启动一次桌面版以初始化 SQLite 数据库后，运行 `backend/scripts/create_admin.py`，并显式指定桌面数据文件：

```powershell
$python = "$env:ProgramFiles\Fly Arrangement\resources\runtime\backend-venv\Scripts\python.exe"
$script = "$env:ProgramFiles\Fly Arrangement\resources\backend\scripts\create_admin.py"
$database = "sqlite+aiosqlite:///C:/ProgramData/FlyArrangement/data/fly_arrangement.db"
& $python $script --database-url $database
```

该命令会提示输入用户名和至少 12 个字符的密码。已有数据库中的管理员账号保持不变。

## 构建安装包

准备好后端运行时、Node 运行时和前端构建产物后：

```powershell
cd desktop
npm ci
npm run dist
```

NSIS 安装包输出到 `desktop/release/`。打包资源包含 backend、frontend 和 `runtime/`；生成的运行时、`node_modules`、安装包、日志与 SQLite 数据库不会加入源码仓库。

卸载程序默认保留 `C:\ProgramData\FlyArrangement`，以免删除用户数据。桌面模式不启用飞书公网 Webhook；需要飞书回调时请部署服务端模式。
