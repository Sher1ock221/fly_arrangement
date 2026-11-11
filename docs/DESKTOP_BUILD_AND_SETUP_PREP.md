# Fly Arrangement 桌面版构建与安装包准备说明

## 一、当前已完成能力

截至当前阶段，桌面版改造已具备以下能力：

1. SQLite baseline 初始化通过；
2. 后端桌面启动脚本通过；
3. 前端桌面启动脚本通过；
4. Electron 开发态启动通过；
5. Electron 能托管前后端进程；
6. Electron 退出后能释放 `13000 / 18000` 端口；
7. 日志目录已能生成 `backend.log`、`frontend.log`、`electron.log`。

## 二、开发态与生产态区别

当前开发态依赖本机环境准备：

1. 本机已安装 Python；
2. 本机已执行 `pip install -r backend/requirements.txt`；
3. 本机已安装 Node.js；
4. `frontend/node_modules` 已存在；
5. `frontend/.next` 已存在；
6. `desktop/node_modules` 已存在；
7. 通过 `npm run start` 启动 Electron。

生产态安装包不能依赖用户手动准备上述环境，应由安装包携带必要运行时与构建产物。

## 三、推荐生产目录结构

建议安装后目录结构如下。

程序目录：

`C:\Program Files\FlyArrangement\`

建议包含：

- `C:\Program Files\FlyArrangement\desktop\`
- `C:\Program Files\FlyArrangement\backend\`
- `C:\Program Files\FlyArrangement\frontend\`
- `C:\Program Files\FlyArrangement\runtime\`
- `C:\Program Files\FlyArrangement\tools\`

数据目录：

`C:\ProgramData\FlyArrangement\`

建议包含：

- `C:\ProgramData\FlyArrangement\data\`
- `C:\ProgramData\FlyArrangement\logs\`
- `C:\ProgramData\FlyArrangement\config\`
- `C:\ProgramData\FlyArrangement\backups\`

## 四、生产态运行时依赖策略

第一版推荐策略：

1. 后端暂时使用 Python venv 随包分发，不做 PyInstaller；
2. 前端使用已 build 的 Next.js 产物；
3. Electron 使用 `electron-builder` 或 Inno Setup 打包；
4. SQLite 不需要单独安装；
5. 不安装 PostgreSQL；
6. 不安装 Docker；
7. 不注册 Windows 服务；
8. 不做开机自启。

## 五、后端生产打包准备

后端侧需准备以下产物：

1. `backend` 源码；
2. `backend/requirements.txt`；
3. Python venv 或嵌入式 Python；
4. 已安装依赖的 `site-packages`；
5. `start_desktop_backend.ps1`；
6. `init_sqlite_baseline.py`；
7. 默认 `DataRoot` 切换到 `C:\ProgramData\FlyArrangement`；
8. 后端启动命令仍使用 `uvicorn app.main:app`。

第一版不建议直接采用 PyInstaller 的原因：

1. FastAPI/服务模块存在较多动态导入路径；
2. SQLAlchemy/Alembic/部分依赖在单文件打包下容易出现动态加载问题；
3. 当前阶段目标是优先保证安装可用与可维护，不优先追求单文件体积。

后端 runtime 准备命令（仅开发机/打包机执行）：

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\scripts\prepare_backend_runtime.ps1
```

说明：

- 推荐 Python 3.11 / 3.12 作为打包机解释器；
- 该脚本会创建 `runtime/backend-venv` 并安装 `backend/requirements.txt`；
- 生成的 `runtime/backend-venv` 应通过 `electron-builder` 的 `extraResources` 一并带入安装包；
- 打包映射应为 `runtime/ -> process.resourcesPath/runtime`；
- 生产态后端脚本会优先使用 `process.resourcesPath/runtime/backend-venv/Scripts/python.exe`；
- 若 `runtime/backend-venv` 缺失，安装包将大概率只能回退系统 Python，终端用户电脑上通常无法运行；
- 该脚本**不在用户电脑执行**，仅用于准备打包产物。

## 六、前端生产打包准备

前端侧需准备以下产物：

1. `frontend/.next`；
2. `frontend/public`；
3. `frontend/package.json`；
4. 必要的 `node_modules`；
5. `start_desktop_frontend.ps1`；
6. 第一版继续使用 `next start`；
7. 当前 `next.config.js` 为 `output: standalone`，后续可评估独立运行优化。

说明：

- 若采用 Next standalone 运行形态，可进一步缩减 `frontend/node_modules` 体积；
- 该优化需要单独回归测试，不在本阶段完成。

## 七、Electron 生产打包准备

Electron 壳需准备：

1. `desktop/package.json`；
2. `desktop/main.js`；
3. `desktop/preload.js`；
4. Electron 依赖；
5. 生产态 `DataRoot` 切换到 `C:\ProgramData\FlyArrangement`；
6. 生产态项目根路径不再是源码仓库，而是安装目录；
7. Electron 主进程需要可从安装目录定位 backend/frontend 脚本。

## 八、安装器选择建议

### 方案 A：electron-builder

优点：

- Electron 应用打包链路成熟；
- 可直接产出 NSIS `setup.exe`；
- 对 Electron 主程序集成友好。

缺点：

- 需要把 backend/frontend/runtime 通过 `extraResources` 一并打包；
- 目录映射与相对路径规则需细致配置和验证。

### 方案 B：Inno Setup

优点：

- 安装流程可控性高；
- 适合多目录、多运行时组合分发；
- 卸载保留数据提示更容易定制。

缺点：

- Electron 构建与安装器可能拆分成两步流程；
- 维护成本高于纯 electron-builder。

推荐结论：

- 第一版优先采用 **electron-builder + extraResources**；
- 若后续对卸载/升级流程有更复杂定制需求，再引入 Inno Setup。

## 九、卸载与数据保留策略

卸载策略建议如下：

1. 卸载默认保留 `C:\ProgramData\FlyArrangement`；
2. 用户核心数据为 SQLite 数据库文件；
3. 日志与备份目录默认保留；
4. 后续可增加“彻底删除数据”的高级卸载选项；
5. 不能默认删除用户数据。

## 十、升级策略

第一版升级策略：

1. 用户安装新版 `setup.exe` 覆盖旧版本；
2. 升级前备份 SQLite 文件；
3. 备份目录为 `C:\ProgramData\FlyArrangement\backups`；
4. 当前阶段不做自动更新；
5. 不接入 WinSparkle；
6. 后续再扩展版本检查与下载能力。

## 十一、打包前验收清单

打包前建议必须通过以下检查：

1. backend 启动脚本可独立运行；
2. frontend 启动脚本可独立运行；
3. Electron 开发态可运行；
4. 关闭 Electron 后端口释放；
5. 新 `DataRoot` 冷启动可生成 SQLite；
6. `/health` 正常；
7. 前端首页正常；
8. 登录流程可用；
9. 常用项目/客户/日程功能可用；
10. 日志正常写入；
11. 无残留端口；
12. 卸载不会误删数据。

## 十二、下一阶段建议

建议按以下阶段推进：

- **Phase 17**：调整 Electron 支持开发态/生产态路径；
- **Phase 18**：新增 electron-builder 配置；
- **Phase 19**：准备 backend venv 生产产物；
- **Phase 20**：准备 frontend standalone 或 build 产物；
- **Phase 21**：首次生成 `setup.exe`；
- **Phase 22**：干净 Windows 机器安装测试；
- **Phase 23**：卸载、升级、数据保留测试。

