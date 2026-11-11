"use strict";

const { app, BrowserWindow, dialog } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");
const http = require("http");

const BACKEND_PORT = 18000;
const FRONTEND_PORT = 13000;
const BACKEND_HEALTH_URL = `http://127.0.0.1:${BACKEND_PORT}/health`;
const FRONTEND_URL = `http://127.0.0.1:${FRONTEND_PORT}`;

const BACKEND_HOST = "127.0.0.1";
const FRONTEND_HOST = "127.0.0.1";
const STARTUP_TIMEOUT_MS = 60 * 1000;
const RETRY_INTERVAL_MS = 1000;
const PROD_DATA_ROOT = "C:\\ProgramData\\FlyArrangement";

let runtimeConfig = null;

let backendProc = null;
let frontendProc = null;
let mainWindow = null;
let cleanupStarted = false;

function ensureDirs() {
  fs.mkdirSync(runtimeConfig.logsDir, { recursive: true });
}

function log(message) {
  const line = `[${new Date().toISOString()}] ${message}`;
  try {
    fs.appendFileSync(runtimeConfig.electronLogPath, `${line}\n`, "utf8");
  } catch (_) {
    // 忽略日志写入失败，避免影响主流程
  }
  console.log(line);
}

function readTailLines(absPath, maxLines) {
  try {
    if (!fs.existsSync(absPath)) {
      return "(log file missing)";
    }
    const raw = fs.readFileSync(absPath, "utf8");
    const lines = raw.split(/\r?\n/);
    const slice = lines.slice(Math.max(0, lines.length - maxLines));
    return slice.join("\n");
  } catch (e) {
    return `(read error: ${e.message})`;
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function probeHttpOkOnce(url, timeoutMs) {
  return new Promise((resolve) => {
    let settled = false;
    const done = (v) => {
      if (settled) return;
      settled = true;
      resolve(v);
    };
    /** @type {import('http').ClientRequest | null} */
    let req = null;
    const timer = setTimeout(() => {
      try {
        if (req) req.destroy();
      } catch (_) {}
      done(false);
    }, timeoutMs);
    req = http.get(url, (res) => {
      clearTimeout(timer);
      const ok =
        res.statusCode && res.statusCode >= 200 && res.statusCode < 300;
      res.resume();
      done(!!ok);
    });
    req.on("error", () => {
      clearTimeout(timer);
      done(false);
    });
  });
}

function waitForHttpOk(url, timeoutMs) {
  const startedAt = Date.now();

  return new Promise((resolve, reject) => {
    const probe = () => {
      const req = http.get(url, (res) => {
        const ok = res.statusCode && res.statusCode >= 200 && res.statusCode < 500;
        res.resume();
        if (ok) {
          resolve(true);
          return;
        }
        if (Date.now() - startedAt >= timeoutMs) {
          reject(new Error(`Timeout waiting for ${url}, status=${res.statusCode}`));
          return;
        }
        setTimeout(probe, RETRY_INTERVAL_MS);
      });

      req.on("error", () => {
        if (Date.now() - startedAt >= timeoutMs) {
          reject(new Error(`Timeout waiting for ${url}`));
          return;
        }
        setTimeout(probe, RETRY_INTERVAL_MS);
      });
    };

    probe();
  });
}

function startPowerShellScript(scriptPath, args, name) {
  const psArgs = [
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    scriptPath,
    ...args,
  ];

  const child = spawn("powershell.exe", psArgs, {
    cwd: runtimeConfig.projectRoot,
    windowsHide: true,
    stdio: "ignore",
  });

  log(`${name} started pid=${child.pid} script=${scriptPath}`);
  child.on("exit", (code, signal) => {
    log(`${name} exited pid=${child.pid} code=${code} signal=${signal}`);
    if (code !== 0 && code !== null) {
      const errRel =
        name === "backend_ps" ? "backend.log.err" : "frontend.log.err";
      const errPath = path.join(runtimeConfig.dataRoot, "logs", errRel);
      const tail = readTailLines(errPath, 80);
      log(`${name}_log_err_path=${errPath}`);
      log(`${name}_log_err_tail_last80=\n${tail}`);
      if (name === "backend_ps") {
        const bootPath = path.join(
          runtimeConfig.dataRoot,
          "logs",
          "backend.log"
        );
        log(`backend_diagnostic_log_tail_last40=\n${readTailLines(bootPath, 40)}`);
      }
      if (name === "frontend_ps") {
        const fBoot = path.join(
          runtimeConfig.dataRoot,
          "logs",
          "frontend.log"
        );
        log(`frontend_diagnostic_log_tail_last40=\n${readTailLines(fBoot, 40)}`);
      }
    }
  });

  return child;
}

function resolveRuntimeConfig() {
  const isPackaged = app.isPackaged === true;
  const mode = isPackaged ? "production" : "development";

  const appPath = app.getAppPath();
  const resourceRoot = process.resourcesPath;
  const projectRoot = isPackaged
    ? resourceRoot
    : path.resolve(__dirname, "..");
  const dataRoot = isPackaged
    ? PROD_DATA_ROOT
    : path.join(projectRoot, "desktop-data-electron");
  const logsDir = path.join(dataRoot, "logs");
  const electronLogPath = path.join(logsDir, "electron.log");
  const backendScript = path.join(
    projectRoot,
    "backend",
    "scripts",
    "start_desktop_backend.ps1"
  );
  const frontendScript = path.join(
    projectRoot,
    "frontend",
    "scripts",
    "start_desktop_frontend.ps1"
  );

  return {
    mode,
    isPackaged,
    appPath,
    resourceRoot,
    projectRoot,
    dataRoot,
    logsDir,
    electronLogPath,
    backendScript,
    frontendScript,
  };
}

async function failFastAndQuit(message) {
  const beAlive = await probeHttpOkOnce(BACKEND_HEALTH_URL, 1200);
  const feAlive = await probeHttpOkOnce(FRONTEND_URL, 1200);
  log(`startup_error=${message}`);
  log(`backend_alive=${beAlive}`);
  log(`frontend_alive=${feAlive}`);
  const backendErr = path.join(runtimeConfig.dataRoot, "logs", "backend.log.err");
  const backendBoot = path.join(runtimeConfig.dataRoot, "logs", "backend.log");
  const frontendBoot = path.join(runtimeConfig.dataRoot, "logs", "frontend.log");
  const frontendErr = path.join(runtimeConfig.dataRoot, "logs", "frontend.log.err");
  log(`backend_diagnostic_tail=\n${readTailLines(backendBoot, 40)}`);
  log(`frontend_diagnostic_tail=\n${readTailLines(frontendBoot, 40)}`);
  log(`backend_err_tail=\n${readTailLines(backendErr, 80)}`);
  log(`frontend_err_tail=\n${readTailLines(frontendErr, 80)}`);
  dialog.showErrorBox(
    "Fly Arrangement 启动失败",
    `${message}\n\n请检查日志目录：\n${runtimeConfig.logsDir}\n\n常见原因：\n- 后端未使用便携 Python（需 resources/runtime/python）\n- 前端缺少 Node 运行时（需 resources/runtime/node/node.exe）或 standalone 未随包构建\n- 18000/13000 端口被占用\n- 对 ProgramData 或安装目录无写权限`
  );
  app.quit();
}

async function validatePaths() {
  try {
    fs.mkdirSync(runtimeConfig.dataRoot, { recursive: true });
    fs.mkdirSync(runtimeConfig.logsDir, { recursive: true });
  } catch (err) {
    await failFastAndQuit(`DataRoot/logs 创建失败：${err.message}`);
    return false;
  }

  if (!fs.existsSync(runtimeConfig.backendScript)) {
    await failFastAndQuit(`后端脚本不存在：${runtimeConfig.backendScript}`);
    return false;
  }
  if (!fs.existsSync(runtimeConfig.frontendScript)) {
    await failFastAndQuit(`前端脚本不存在：${runtimeConfig.frontendScript}`);
    return false;
  }
  return true;
}

function killProcessTree(pid, name) {
  return new Promise((resolve) => {
    if (!pid) {
      resolve();
      return;
    }

    log(`cleanup_start name=${name} pid=${pid}`);
    const killer = spawn("taskkill", ["/PID", String(pid), "/T", "/F"], {
      windowsHide: true,
      stdio: "ignore",
    });

    killer.on("exit", (code) => {
      log(`cleanup_done name=${name} pid=${pid} taskkill_exit=${code}`);
      resolve();
    });
    killer.on("error", (err) => {
      log(`cleanup_error name=${name} pid=${pid} err=${err.message}`);
      resolve();
    });
  });
}

async function cleanupChildProcesses() {
  if (cleanupStarted) return;
  cleanupStarted = true;

  await killProcessTree(frontendProc && frontendProc.pid, "frontend_ps");
  await killProcessTree(backendProc && backendProc.pid, "backend_ps");
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    title: "Fly Arrangement",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.js"),
    },
  });

  mainWindow.loadURL(FRONTEND_URL);
}

async function bootstrap() {
  runtimeConfig = resolveRuntimeConfig();
  ensureDirs();
  log("electron_start");
  log(`mode=${runtimeConfig.mode}`);
  log(`app_is_packaged=${runtimeConfig.isPackaged}`);
  log(`app_path=${runtimeConfig.appPath}`);
  log(`resources_path=${runtimeConfig.resourceRoot}`);
  log(`project_root=${runtimeConfig.projectRoot}`);
  log(`data_root=${runtimeConfig.dataRoot}`);
  log(`backend_script=${runtimeConfig.backendScript}`);
  log(`frontend_script=${runtimeConfig.frontendScript}`);

  if (!(await validatePaths())) {
    return;
  }

  backendProc = startPowerShellScript(
    runtimeConfig.backendScript,
    ["-DataRoot", runtimeConfig.dataRoot, "-Port", String(BACKEND_PORT)],
    "backend_ps"
  );

  frontendProc = startPowerShellScript(
    runtimeConfig.frontendScript,
    [
      "-DataRoot",
      runtimeConfig.dataRoot,
      "-Port",
      String(FRONTEND_PORT),
      "-ApiBaseUrl",
      `http://${BACKEND_HOST}:${BACKEND_PORT}`,
    ],
    "frontend_ps"
  );

  try {
    await waitForHttpOk(BACKEND_HEALTH_URL, STARTUP_TIMEOUT_MS);
    log("backend_ready=true");
    await waitForHttpOk(FRONTEND_URL, STARTUP_TIMEOUT_MS);
    log("frontend_ready=true");
  } catch (err) {
    const be = path.join(runtimeConfig.dataRoot, "logs", "backend.log.err");
    const bb = path.join(runtimeConfig.dataRoot, "logs", "backend.log");
    const fb = path.join(runtimeConfig.dataRoot, "logs", "frontend.log");
    const fe = path.join(runtimeConfig.dataRoot, "logs", "frontend.log.err");
    const beAlive = await probeHttpOkOnce(BACKEND_HEALTH_URL, 1200);
    const feAlive = await probeHttpOkOnce(FRONTEND_URL, 1200);
    log(`startup_error=${err.message}`);
    log(`backend_alive=${beAlive}`);
    log(`frontend_alive=${feAlive}`);
    log(`backend_diagnostic_tail=\n${readTailLines(bb, 40)}`);
    log(`frontend_diagnostic_tail=\n${readTailLines(fb, 40)}`);
    log(`backend_err_tail=\n${readTailLines(be, 80)}`);
    log(`frontend_err_tail=\n${readTailLines(fe, 80)}`);
    dialog.showErrorBox(
      "Fly Arrangement 启动失败",
      `服务在 ${Math.floor(STARTUP_TIMEOUT_MS / 1000)} 秒内未就绪。\n请检查日志目录：\n${runtimeConfig.logsDir}\n\n错误：${err.message}\n\n请查看 electron.log 中的 backend_err_tail / frontend_err_tail。\n常见原因：便携 Python / Node 未随包、端口占用、权限不足。`
    );
    await cleanupChildProcesses();
    app.quit();
    return;
  }

  createMainWindow();
}

app.whenReady().then(bootstrap).catch(async (err) => {
  log(`fatal_error=${err.message}`);
  if (runtimeConfig && runtimeConfig.dataRoot) {
    const beAlive = await probeHttpOkOnce(BACKEND_HEALTH_URL, 1200);
    const feAlive = await probeHttpOkOnce(FRONTEND_URL, 1200);
    log(`backend_alive=${beAlive}`);
    log(`frontend_alive=${feAlive}`);
    const be = path.join(runtimeConfig.dataRoot, "logs", "backend.log.err");
    const bb = path.join(runtimeConfig.dataRoot, "logs", "backend.log");
    const fb = path.join(runtimeConfig.dataRoot, "logs", "frontend.log");
    const fe = path.join(runtimeConfig.dataRoot, "logs", "frontend.log.err");
    log(`backend_diagnostic_tail=\n${readTailLines(bb, 40)}`);
    log(`frontend_diagnostic_tail=\n${readTailLines(fb, 40)}`);
    log(`backend_err_tail=\n${readTailLines(be, 80)}`);
    log(`frontend_err_tail=\n${readTailLines(fe, 80)}`);
  }
  await cleanupChildProcesses();
  app.quit();
});

app.on("before-quit", async () => {
  await cleanupChildProcesses();
});

app.on("will-quit", async () => {
  await cleanupChildProcesses();
});

app.on("window-all-closed", async () => {
  await cleanupChildProcesses();
  if (process.platform !== "darwin") {
    app.quit();
  }
});
