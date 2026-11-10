"""Windowed local EXE entry point; serves local assets and uses Edge's app window."""
import ctypes
import json
import logging
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.request

MUTEX_NAME = r"Local\VariableWorkbench.Desktop.8765"
URL = "http://127.0.0.1:8765"


def ready(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url + "/api/health", timeout=1) as response:
        return json.load(response).get("application") == "variable-workbench"


def wait_ready(url, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if ready(url):
                return
        except OSError:
            pass
        time.sleep(0.1)
    raise RuntimeError("本地服务未能启动，请查看 state/startup.log")


def open_edge(state_dir):
    candidates = [Path(os.environ[name]) / "Microsoft/Edge/Application/msedge.exe"
                  for name in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")
                  if os.environ.get(name)]
    edge = next((path for path in candidates if path.is_file()), None)
    if not edge:
        raise RuntimeError("本地窗口需要系统 Microsoft Edge，请安装后重试。")
    command = [str(edge), "--app=" + URL, "--user-data-dir=" + str(state_dir / "desktop-profile"),
               "--no-first-run", "--no-default-browser-check", "--disable-background-networking"]
    # System Edge must start with the normal Windows DLL search path.
    bundled_dir = getattr(sys, "_MEIPASS", None)
    if bundled_dir:
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    try:
        subprocess.Popen(command)
    finally:
        if bundled_dir:
            ctypes.windll.kernel32.SetDllDirectoryW(str(bundled_dir))


def run_owner():
    import workbench

    logging.basicConfig(filename=workbench.STATE / "startup.log", level=logging.INFO,
                        format="%(asctime)s [%(process)d] %(message)s", encoding="utf-8")
    workbench.initialize()
    server = workbench.ThreadingHTTPServer(("127.0.0.1", 8765), workbench.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        wait_ready(URL)
        logging.info("Local service ready; opening application window")
        open_edge(workbench.STATE)
        # Chromium may hand off to an existing process for the app profile.
        # A refresh sends pagehide too, but the new page sends a fresh heartbeat.
        while time.monotonic() - workbench.WINDOW_ACTIVITY < 180:
            closed_at = workbench.WINDOW_CLOSED_AT
            if closed_at and time.monotonic() - closed_at >= 8:
                break
            time.sleep(0.5)
        logging.info("Stopping local service after the window closed or went idle")
    finally:
        server.shutdown()
        server.server_close()
        if workbench.PORT:
            workbench.PORT.close()
        workbench.API.clear()


def main():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel.CloseHandle.restype = ctypes.c_int
    instance = kernel.CreateMutexW(None, False, MUTEX_NAME)
    error = ctypes.get_last_error()
    if not instance:
        raise ctypes.WinError(error)
    try:
        if error != 183:  # ERROR_ALREADY_EXISTS
            run_owner()
    finally:
        kernel.CloseHandle(instance)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if len(sys.argv) == 1:
        try:
            main()
        except Exception as error:
            logging.exception("Desktop startup failed")
            ctypes.windll.user32.MessageBoxW(None, str(error), "变量工作台 · 启动失败", 0x10)
