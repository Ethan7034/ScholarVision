import requests
import time
import os
import re

LOCAL_URL = "http://localhost:8000"
LOG_FILE = "tunnel_log.txt"

def get_tunnel_url():
    if not os.path.exists(LOG_FILE):
        return None
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            content = f.read()
            urls = re.findall(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', content)
            if urls:
                return urls[-1]
    except Exception as e:
        print(f"⚠️ Failure: {e}")
    return None

print("🚀 Connection Guardian Engine has launched.\n👁Extracting web links...")

current_tunnel_url = None
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

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
        
        current_tunnel_url = None 
    
    time.sleep(30)