"""
Tunnel watchdog ("connection guardian").

Keeps a Cloudflare quick tunnel alive and self-healing:

  1. Every 30 seconds it pings the local API and the public tunnel URL. The
     periodic traffic alone prevents idle-connection teardown.
  2. On failure it distinguishes the two causes: a transient network blip is
     ignored, while a dead cloudflared process triggers an automatic restart
     using the project-local cloudflared.exe. The fresh URL lands in the same
     log file and is picked up on the next pass.

All paths resolve relative to this script's own directory, so behavior is
identical whether launched by double-click or by start_server.bat.
"""

import os
import re
import subprocess
import time
from pathlib import Path

import requests

# 全部改成脚本所在目录的绝对定位：双击运行或被 start_server 拉起时 cwd 都可能不同
BASE_DIR = Path(__file__).resolve().parent
LOCAL_URL = "http://localhost:8000"
LOG_FILE = BASE_DIR / "tunnel_log.txt"
CLOUDFLARED = BASE_DIR / "cloudflared.exe"

URL_PATTERN = re.compile(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com')

# Windows: 后台拉起进程不弹黑窗
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def get_tunnel_url():
    """Latest tunnel URL found in the log (last match = newest restart)."""
    if not os.path.exists(LOG_FILE):
        return None
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
            urls = URL_PATTERN.findall(content)
            if urls:
                return urls[-1]  # 重启后日志里是最新 URL，取最后一个
    except Exception as e:
        print(f"⚠️ Failure: {e}")
    return None


def cloudflared_running():
    """True while any cloudflared process lives.

    On detection failure we conservatively report "running" -- a false
    negative here would spawn duplicate tunnels.
    """
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq cloudflared.exe"],
            capture_output=True, text=True,
        ).stdout
        return "cloudflared.exe" in out
    except Exception:
        # 检测本身失败时保守当作"活着"，避免误杀重启出一堆实例
        return True


def restart_tunnel():
    """Relaunch the tunnel after its process died, appending to the same log."""
    if not CLOUDFLARED.exists():
        print(f"❌ 无法重启隧道：{CLOUDFLARED} 不存在")
        return False
    try:
        log_fh = open(LOG_FILE, "a", encoding="utf-8", errors="replace")
        proc = subprocess.Popen(
            [
                str(CLOUDFLARED), "tunnel",
                "--url", "http://127.0.0.1:8000",
                "--protocol", "http2",
            ],
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            cwd=str(BASE_DIR),
            creationflags=_NO_WINDOW,
        )
        # Popen 已让子进程继承句柄，父进程这份立刻关掉（否则每次重启泄漏一个句柄）
        log_fh.close()
        print("🔄 cloudflared 进程已不在，已重新拉起隧道（等待新 URL 写入日志…）")
        return True
    except Exception as e:
        print(f"❌ 重启隧道失败: {e}")
        return False


headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def run_forever():
    """Main loop: keep-alive probe, URL refresh, crash recovery."""
    print("🚀 Connection Guardian Engine has launched.\n👁Extracting web links...")
    current_tunnel_url = None

    while True:
        if not current_tunnel_url:
            current_tunnel_url = get_tunnel_url()
            if current_tunnel_url:
                print(f"✅ Weblink: {current_tunnel_url}")
            else:
                print(f"[{time.strftime('%H:%M:%S')}] Waiting for the log generation link... (ensure cloudflared is running)")
                time.sleep(3)
                continue

        try:
            requests.get(LOCAL_URL, headers=headers, timeout=5)

            res = requests.get(current_tunnel_url, headers=headers, timeout=10)
            print(f"[{time.strftime('%H:%M:%S')}], ✅ACCESS! status: {res.status_code}, target: {current_tunnel_url}")

        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] ⚠️Connection ERROR: {e}")
            # 断联先分清是"隧道进程死了"还是"瞬时抖动"，前者才需要重启
            if not cloudflared_running():
                restart_tunnel()
            current_tunnel_url = None

        time.sleep(30)


if __name__ == "__main__":
    run_forever()
