"""Windowed local EXE entry point; serves local assets and uses Edge's app window."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import logging
import urllib.request

import workbench


def ready(url):
    # Local health probes must never be routed through system HTTP proxies.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url + "/api/health", timeout=1) as response:
        return json.load(response).get("application") == "variable-workbench"


def wait_ready(url, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if ready(url): return
        except OSError:
            pass
        time.sleep(0.1)
    raise RuntimeError("本地服务未能启动，请查看 state/startup.log")


def main():
    # Reopening the shortcut reuses an existing workbench instance.
    url = "http://127.0.0.1:8765"
    server = None
    logging.basicConfig(filename=workbench.STATE / "startup.log", level=logging.INFO,
                        format="%(asctime)s %(message)s", encoding="utf-8")
    try:
        running = ready(url)
    except OSError:
        running = False
    if not running:
        workbench.initialize()
        try:
            server = workbench.ThreadingHTTPServer(("127.0.0.1", 8765), workbench.Handler)
        except OSError as error:
            if getattr(error, "winerror", None) != 10048 and error.errno != 98: raise
            # A second shortcut launch may have started the owner while we scanned.
        if server:
            threading.Thread(target=server.serve_forever, daemon=True).start()
    wait_ready(url)
    logging.info("Local service ready; opening application window")
    candidates = [Path(os.environ.get(name, "")) / "Microsoft/Edge/Application/msedge.exe"
                  for name in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    edge = next((path for path in candidates if path.is_file()), None)
    if not edge:
        raise RuntimeError("本地窗口需要系统 Microsoft Edge，请安装后重试。")
    try:
        process = subprocess.Popen([str(edge), "--app=" + url,
            "--user-data-dir=" + str(workbench.STATE / "desktop-profile"),
            "--no-first-run", "--no-default-browser-check", "--disable-background-networking"])
        if server:
            # Edge's launcher can exit after handing off to an existing browser.
            # Keep the service alive using page activity, not that launcher PID.
            while time.monotonic() - workbench.WINDOW_ACTIVITY < 180:
                time.sleep(1)
            logging.info("No page activity for 180 seconds; stopping local service")
    finally:
        if server:
            server.shutdown()
            server.server_close()
            if workbench.PORT: workbench.PORT.close()
            workbench.API.clear()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        ctypes.windll.user32.MessageBoxW(None, str(error), "变量工作台 · 启动失败", 0x10)
