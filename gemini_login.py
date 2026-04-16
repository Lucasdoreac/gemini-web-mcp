#!/usr/bin/env python3
"""
Login Gemini Web via CDP — mesmo padrão do nlm login.
Lança Chrome via subprocess, polling de URL via WebSocket CDP.
Execute direto no terminal: python gemini-login.py
"""
import json
import subprocess
import sys
import time
from pathlib import Path

try:
    import websocket
except ImportError:
    print("Instale: pip install websocket-client")
    sys.exit(1)

CHROME   = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CDP_PORT = 9223
STATE_DIR = Path(__file__).parent / ".goon_state" / "chrome_profile"
STORAGE_FILE = STATE_DIR / "storage_state.json"
STATE_DIR.mkdir(parents=True, exist_ok=True)


def cdp(ws_url: str, method: str, params: dict = {}) -> dict:
    ws = websocket.create_connection(ws_url, timeout=10)
    ws.send(json.dumps({"id": 1, "method": method, "params": params}))
    while True:
        r = json.loads(ws.recv())
        if r.get("id") == 1:
            ws.close()
            return r.get("result", {})


def get_debugger_url(port: int, tries: int = 20) -> str | None:
    import urllib.request
    for _ in range(tries):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
                return json.loads(r.read()).get("webSocketDebuggerUrl", "").replace("localhost", "127.0.0.1")
        except Exception:
            time.sleep(0.5)
    return None


def get_current_url(ws_url: str) -> str:
    try:
        r = cdp(ws_url, "Runtime.evaluate", {"expression": "window.location.href"})
        return r.get("result", {}).get("value", "")
    except Exception:
        return ""


def get_all_cookies(ws_url: str) -> list:
    try:
        return cdp(ws_url, "Network.getAllCookies").get("cookies", [])
    except Exception:
        return []


def find_or_open_gemini_tab(port: int) -> str | None:
    """Find Gemini tab or open one, return its WS debugger URL."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=5) as r:
            pages = json.loads(r.read())
    except Exception:
        return None

    for p in pages:
        if "gemini.google.com" in p.get("url", ""):
            return p.get("webSocketDebuggerUrl", "").replace("localhost", "127.0.0.1")

    # Open new tab
    try:
        import urllib.request
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/json/new?https://gemini.google.com/app",
            method="PUT"
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            p = json.loads(r.read())
            return p.get("webSocketDebuggerUrl", "").replace("localhost", "127.0.0.1")
    except Exception:
        return None


def save_storage_state(cookies: list) -> None:
    """Save cookies in Playwright storage_state format."""
    state = {"cookies": cookies, "origins": []}
    STORAGE_FILE.write_text(json.dumps(state, indent=2))
    print(f"[LOGIN] Sessão salva ({STORAGE_FILE.stat().st_size} bytes) → {STORAGE_FILE}")


def main():
    print(f"[LOGIN] Lançando Chrome na porta {CDP_PORT}...")
    proc = subprocess.Popen([
        CHROME,
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={STATE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        f"--remote-allow-origins=http://127.0.0.1:{CDP_PORT}",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    debugger_url = get_debugger_url(CDP_PORT, tries=30)
    if not debugger_url:
        print("[LOGIN] Falha ao conectar ao Chrome CDP.")
        proc.terminate()
        sys.exit(1)

    ws_url = find_or_open_gemini_tab(CDP_PORT)
    if not ws_url:
        print("[LOGIN] Falha ao abrir aba do Gemini.")
        proc.terminate()
        sys.exit(1)

    print("[LOGIN] Chrome aberto. Faça login completo (email, senha, 2FA)...")
    print("[LOGIN] Aguardando cookies de autenticação (timeout: 5 min)...")

    # Poll cookies until SAPISID appears — same approach as nlm
    deadline = time.time() + 300
    while time.time() < deadline:
        cookies = get_all_cookies(ws_url)
        auth = [c for c in cookies if c.get("name") in ("SAPISID", "SID") and "google" in c.get("domain", "")]
        if auth:
            print(f"[LOGIN] Autenticação detectada ({len(auth)} auth cookies).")
            time.sleep(2)  # let remaining cookies settle
            break
        time.sleep(1)
    else:
        print("[LOGIN] Timeout. Salvando estado atual...")

    cookies = get_all_cookies(ws_url)
    google_cookies = [c for c in cookies if "google" in c.get("domain", "")]
    print(f"[LOGIN] {len(google_cookies)} cookies Google capturados.")
    save_storage_state(cookies)

    proc.terminate()


if __name__ == "__main__":
    main()
