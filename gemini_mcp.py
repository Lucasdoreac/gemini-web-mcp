#!/usr/bin/env python3
"""
Gemini Web MCP Server — Playwright-based automation.
Exposes Gemini Web UI as MCP tools via stdio (JSON-RPC 2.0).

Setup:
  claude mcp add --scope user gemini-web python C:/Users/lucas/DR/src/gemini_mcp.py
"""
import asyncio
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stdin  = io.TextIOWrapper(sys.stdin.buffer,  encoding="utf-8", errors="replace")

STATE_DIR    = Path(__file__).parent.parent / ".goon_state" / "chrome_profile"
STORAGE_FILE = STATE_DIR / "storage_state.json"
CHROME       = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

INPUT_SELS = [
    'rich-textarea div[contenteditable="true"]',
    'div[contenteditable="true"]',
    'textarea',
]
STOP_SELS = "button[aria-label='Stop response'], button[aria-label='Parar resposta'], button[aria-label='Enviar mensagem']"
RESP_SELS = [
    "model-response .response-content",
    "message-content .markdown",
    ".response-container-content",
    "model-response",
]

_pw   = None
_ctx  = None
_page = None


async def _ensure_browser():
    global _pw, _ctx, _page
    if _ctx:
        return
    from playwright.async_api import async_playwright
    _pw = await async_playwright().start()
    _ctx = await _pw.chromium.launch_persistent_context(
        user_data_dir=str(STATE_DIR),
        headless=True,
        executable_path=CHROME,
        args=["--no-sandbox", "--disable-gpu"],
    )
    _page = _ctx.pages[0] if _ctx.pages else await _ctx.new_page()
    await _page.goto("https://gemini.google.com/app", timeout=30000)
    await _page.wait_for_load_state("domcontentloaded", timeout=15000)


async def _find_input():
    for s in INPUT_SELS:
        try:
            el = await _page.wait_for_selector(s, timeout=3000)
            if el:
                return s
        except Exception:
            continue
    return None


async def _wait_for_response():
    try:
        await _page.wait_for_selector(STOP_SELS, timeout=10000)
        await _page.wait_for_selector(STOP_SELS, state="hidden", timeout=120000)
    except Exception:
        await asyncio.sleep(8)
    for sel in RESP_SELS:
        els = await _page.query_selector_all(sel)
        if els:
            return await els[-1].inner_text()
    return ""


# ── Tools ────────────────────────────────────────────────────────────────────

async def tool_send_message(prompt: str, new_conversation: bool = False) -> str:
    """Send a message to Gemini and return the response."""
    await _ensure_browser()
    if new_conversation:
        await _page.goto("https://gemini.google.com/app", timeout=15000)
        await _page.wait_for_load_state("domcontentloaded")
    if "accounts.google.com" in _page.url:
        return "Error: session expired. Run: python gemini-login.py"
    sel = await _find_input()
    if not sel:
        return "Error: could not find input field"
    await _page.click(sel)
    await _page.keyboard.type(prompt)
    await _page.keyboard.press("Enter")
    return await _wait_for_response()


async def tool_new_conversation() -> str:
    """Start a new Gemini conversation."""
    await _ensure_browser()
    try:
        btn = await _page.wait_for_selector("button[aria-label='Nova conversa'], button[aria-label='New conversation']", timeout=5000)
        await btn.click()
        await _page.wait_for_load_state("domcontentloaded")
    except Exception:
        await _page.goto("https://gemini.google.com/app", timeout=15000)
        await _page.wait_for_load_state("domcontentloaded")
    return _page.url


async def tool_list_conversations() -> list:
    """List recent conversations from the sidebar."""
    await _ensure_browser()
    await asyncio.sleep(1)
    items = await _page.evaluate("""() => {
        const els = document.querySelectorAll('[aria-label^="Mais opções de"], [aria-label^="More options for"]');
        return [...els].map(el => {
            const label = el.getAttribute('aria-label') || '';
            const title = label.replace(/^(Mais opções de|More options for) /, '').trim();
            const link = el.closest('a') || el.closest('[href]');
            return { title, url: link ? link.href : null };
        });
    }""")
    return items


async def tool_open_conversation(title: str) -> str:
    """Open a conversation by (partial) title match."""
    await _ensure_browser()
    convs = await tool_list_conversations()
    match = next((c for c in convs if title.lower() in c["title"].lower()), None)
    if not match or not match.get("url"):
        return f"Conversation not found: {title}"
    await _page.goto(match["url"], timeout=15000)
    await _page.wait_for_load_state("domcontentloaded")
    return f"Opened: {match['title']}"


async def tool_create_image(prompt: str) -> str:
    """Ask Gemini to create an image and return the response."""
    await _ensure_browser()
    # Click the "Criar imagem" tool button if available
    try:
        btn = await _page.wait_for_selector(
            "button[aria-label*='Criar imagem'], button[aria-label*='Create image']",
            timeout=3000)
        await btn.click()
        await asyncio.sleep(0.5)
    except Exception:
        pass  # fall back to sending as text
    sel = await _find_input()
    if not sel:
        return "Error: could not find input field"
    await _page.click(sel)
    await _page.keyboard.type(prompt)
    await _page.keyboard.press("Enter")
    return await _wait_for_response()


async def tool_upload_file(file_path: str, prompt: str = "") -> str:
    """Upload a file to Gemini and optionally send a prompt about it."""
    await _ensure_browser()
    path = Path(file_path)
    if not path.exists():
        return f"Error: file not found: {file_path}"
    try:
        # Open the file upload menu
        menu_btn = await _page.wait_for_selector(
            "button[aria-label*='menu de envio de arquivo'], button[aria-label*='file']",
            timeout=5000)
        await menu_btn.click()
        await asyncio.sleep(0.5)
        # Find the file input that appears
        file_input = await _page.wait_for_selector("input[type='file']", timeout=5000)
        await file_input.set_input_files(str(path))
        await asyncio.sleep(1)
    except Exception as e:
        return f"Error opening file upload: {e}"
    if prompt:
        sel = await _find_input()
        if sel:
            await _page.click(sel)
            await _page.keyboard.type(prompt)
    await _page.keyboard.press("Enter")
    return await _wait_for_response()


async def tool_list_gems() -> list:
    """List available Gems from the sidebar."""
    await _ensure_browser()
    try:
        gems_btn = await _page.wait_for_selector(
            "button[aria-label='Gems'], a[aria-label='Gems']",
            timeout=3000)
        await gems_btn.click()
        await asyncio.sleep(1)
    except Exception:
        pass
    items = await _page.evaluate("""() => {
        const els = document.querySelectorAll('[data-gem-id], .gem-item, [aria-label*="Gem"]');
        return [...els].map(el => ({
            name: el.textContent?.trim() || el.getAttribute('aria-label') || '',
            id: el.getAttribute('data-gem-id') || ''
        })).filter(g => g.name);
    }""")
    return items


async def tool_get_current_url() -> str:
    """Return the current Gemini page URL (useful as conversation ID)."""
    await _ensure_browser()
    return _page.url


# ── MCP Protocol ─────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "send_message",
        "description": "Send a message to Gemini Web and return the response. Gemini has Google Search built-in for web research.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "new_conversation": {"type": "boolean", "default": False},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "new_conversation",
        "description": "Start a fresh Gemini conversation. Returns the new conversation URL.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_conversations",
        "description": "List recent conversations from the Gemini sidebar.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "open_conversation",
        "description": "Open an existing conversation by partial title match.",
        "inputSchema": {
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
        },
    },
    {
        "name": "create_image",
        "description": "Ask Gemini to generate an image from a text prompt.",
        "inputSchema": {
            "type": "object",
            "properties": {"prompt": {"type": "string"}},
            "required": ["prompt"],
        },
    },
    {
        "name": "upload_file",
        "description": "Upload a local file to Gemini and optionally ask something about it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute path to file"},
                "prompt": {"type": "string", "description": "Optional message about the file"},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "list_gems",
        "description": "List available Gems (custom AI personas) in the user's Gemini account.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_current_url",
        "description": "Get the current Gemini page URL (conversation ID).",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

TOOL_MAP = {
    "send_message":       lambda a: tool_send_message(a["prompt"], a.get("new_conversation", False)),
    "new_conversation":   lambda a: tool_new_conversation(),
    "list_conversations": lambda a: tool_list_conversations(),
    "open_conversation":  lambda a: tool_open_conversation(a["title"]),
    "create_image":       lambda a: tool_create_image(a["prompt"]),
    "upload_file":        lambda a: tool_upload_file(a["file_path"], a.get("prompt", "")),
    "list_gems":          lambda a: tool_list_gems(),
    "get_current_url":    lambda a: tool_get_current_url(),
}


def _resp(id, result):
    return {"jsonrpc": "2.0", "id": id, "result": result}

def _err(id, code, msg):
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": msg}}


async def handle(req: dict):
    id     = req.get("id")
    method = req.get("method", "")
    params = req.get("params", {})

    if method == "initialize":
        return _resp(id, {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "gemini-web", "version": "1.0.0"},
            "capabilities": {"tools": {}},
        })
    if method == "tools/list":
        return _resp(id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {})
        fn = TOOL_MAP.get(name)
        if not fn:
            return _err(id, -32601, f"Unknown tool: {name}")
        try:
            result = await fn(args)
            text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
            return _resp(id, {"content": [{"type": "text", "text": text}]})
        except Exception as e:
            return _err(id, -32000, str(e))
    if method == "notifications/initialized":
        return None
    return _err(id, -32601, f"Method not found: {method}")


async def main():
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer)
    wt, wp = await loop.connect_write_pipe(
        lambda: asyncio.streams.FlowControlMixin(loop=loop), sys.stdout.buffer)
    writer = asyncio.StreamWriter(wt, wp, None, loop)

    while True:
        try:
            line = await reader.readline()
            if not line:
                break
            resp = await handle(json.loads(line.decode()))
            if resp is not None:
                writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode())
                await writer.drain()
        except Exception as e:
            sys.stderr.write(f"[MCP] {e}\n")
            sys.stderr.flush()


if __name__ == "__main__":
    if not STORAGE_FILE.exists():
        sys.stderr.write("No session. Run: python gemini-login.py\n")
        sys.exit(1)
    asyncio.run(main())
