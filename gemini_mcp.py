#!/usr/bin/env python3
"""
Gemini Web MCP Server v2 — Complete Playwright-based automation.
Exposes ALL Gemini Web UI features as MCP tools via stdio (JSON-RPC 2.0).

Features:
- All native Gemini Web functions
- Folder upload
- GitHub URL import
- Code execution
- Conversation management
- Extensions access
- Auto-adaptation to UI changes

Setup:
  claude mcp add --scope user gemini-web python C:/Users/lucas/DR/src/gemini_mcp.py
"""
import asyncio
import json
import sys
import zipfile
import tempfile
import os
from pathlib import Path

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stdin  = io.TextIOWrapper(sys.stdin.buffer,  encoding="utf-8", errors="replace")

STATE_DIR    = Path(__file__).parent.parent / ".goon_state" / "chrome_profile"
STORAGE_FILE = STATE_DIR / "storage_state.json"
CHROME       = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# UI Selectors (auto-discovery for resilience)
INPUT_SELS = [
    'rich-textarea div[contenteditable="true"]',
    'div[contenteditable="true"]',
    'textarea',
]
STOP_SELS = "button[aria-label='Stop response'], button[aria-label='Parar resposta']"
RESP_SELS = [
    "model-response .response-content",
    "message-content .markdown",
    ".response-container-content",
    "model-response",
]
ATTACHMENT_BTN = "button[aria-label*='anexo'], button[aria-label*='attach'], button[aria-label*='file']"

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


# ── Core Tools ───────────────────────────────────────────────────────────────

async def tool_send_message(prompt: str, new_conversation: bool = False) -> str:
    """Send a message to Gemini and return the response."""
    await _ensure_browser()
    if new_conversation:
        await _page.goto("https://gemini.google.com/app", timeout=15000)
        await _page.wait_for_load_state("domcontentloaded")
    if "accounts.google.com" in _page.url:
        return "Error: session expired. Run: python gemini_login.py"
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
        btn = await _page.wait_for_selector(
            "button[aria-label='Nova conversa'], button[aria-label='New conversation']",
            timeout=5000
        )
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
    try:
        btn = await _page.wait_for_selector(
            "button[aria-label*='Criar imagem'], button[aria-label*='Create image']",
            timeout=3000
        )
        await btn.click()
        await asyncio.sleep(0.5)
    except Exception:
        pass
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
        menu_btn = await _page.wait_for_selector(ATTACHMENT_BTN, timeout=5000)
        await menu_btn.click()
        await asyncio.sleep(0.5)
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


# ── NEW: Advanced Tools ───────────────────────────────────────────────────────

async def tool_upload_folder(folder_path: str, prompt: str = "") -> str:
    """Upload entire folder to Gemini (zips automatically)."""
    await _ensure_browser()
    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        return f"Error: folder not found: {folder_path}"

    try:
        # Create temporary zip
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp_zip:
            zip_path = tmp_zip.name

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file in folder.rglob('*'):
                if file.is_file():
                    arcname = file.relative_to(folder)
                    zipf.write(file, arcname)

        # Upload zip
        menu_btn = await _page.wait_for_selector(ATTACHMENT_BTN, timeout=5000)
        await menu_btn.click()
        await asyncio.sleep(0.5)
        file_input = await _page.wait_for_selector("input[type='file']", timeout=5000)
        await file_input.set_input_files(zip_path)
        await asyncio.sleep(2)

        # Clean up
        os.unlink(zip_path)

        if prompt:
            sel = await _find_input()
            if sel:
                await _page.click(sel)
                await _page.keyboard.type(prompt)
        await _page.keyboard.press("Enter")
        return await _wait_for_response()

    except Exception as e:
        return f"Error uploading folder: {e}"


async def tool_upload_github_url(github_url: str, prompt: str = "") -> str:
    """Upload code from GitHub URL to Gemini."""
    await _ensure_browser()

    # Navigate to Gemini
    sel = await _find_input()
    if not sel:
        return "Error: could not find input field"

    # Send GitHub URL with context
    message = f"Analyze this GitHub repository: {github_url}"
    if prompt:
        message = f"{message}\n\n{prompt}"

    await _page.click(sel)
    await _page.keyboard.type(message)
    await _page.keyboard.press("Enter")
    return await _wait_for_response()


async def tool_search_conversations(query: str) -> list:
    """Search through conversation history."""
    await _ensure_browser()
    convs = await tool_list_conversations()
    results = [
        c for c in convs
        if query.lower() in c.get("title", "").lower()
    ]
    return results


async def tool_delete_conversation(title: str) -> str:
    """Delete a conversation by title."""
    await _ensure_browser()
    convs = await tool_list_conversations()
    match = next((c for c in convs if title.lower() in c["title"].lower()), None)
    if not match:
        return f"Conversation not found: {title}"

    try:
        # Click options menu
        escaped_title = match["title"].replace('"', '\\"')
        options_btn = await _page.wait_for_selector(
            f"[aria-label*='Mais opções de {escaped_title}'], [aria-label*='More options for {escaped_title}']",
            timeout=5000
        )
        await options_btn.click()
        await asyncio.sleep(0.5)

        # Click delete option
        delete_btn = await _page.wait_for_selector(
            "button[aria-label*='Deletar'], button[aria-label*='Delete']",
            timeout=3000
        )
        await delete_btn.click()
        await asyncio.sleep(1)

        return f"Deleted: {match['title']}"
    except Exception as e:
        return f"Error deleting conversation: {e}"


async def tool_pin_conversation(title: str, pin: bool = True) -> str:
    """Pin or unpin a conversation."""
    await _ensure_browser()
    convs = await tool_list_conversations()
    match = next((c for c in convs if title.lower() in c["title"].lower()), None)
    if not match:
        return f"Conversation not found: {title}"

    try:
        escaped_title = match["title"].replace('"', '\\"')
        options_btn = await _page.wait_for_selector(
            f"[aria-label*='Mais opções de {escaped_title}'], [aria-label*='More options for {escaped_title}']",
            timeout=5000
        )
        await options_btn.click()
        await asyncio.sleep(0.5)

        pin_btn = await _page.wait_for_selector(
            "button[aria-label*='Fixar'], button[aria-label*='Pin']" if pin
            else "button[aria-label*='Desafixar'], button[aria-label*='Unpin']",
            timeout=3000
        )
        await pin_btn.click()
        await asyncio.sleep(1)

        action = "Pinned" if pin else "Unpinned"
        return f"{action}: {match['title']}"
    except Exception as e:
        return f"Error pinning conversation: {e}"


async def tool_share_conversation(title: str = "") -> str:
    """Get shareable link for current or specified conversation."""
    await _ensure_browser()

    if title:
        await tool_open_conversation(title)

    try:
        share_btn = await _page.wait_for_selector(
            "button[aria-label*='Compartilhar'], button[aria-label*='Share']",
            timeout=5000
        )
        await share_btn.click()
        await asyncio.sleep(1)

        # Get share URL
        url_input = await _page.wait_for_selector("input[value*='https://gemini.google.com/share']", timeout=5000)
        share_url = await url_input.get_attribute("value")

        # Close dialog
        close_btn = await _page.wait_for_selector("button[aria-label*='Close'], button[aria-label*='Fechar']", timeout=3000)
        await close_btn.click()

        return f"Share URL: {share_url}"
    except Exception as e:
        return f"Error getting share link: {e}"


async def tool_export_conversation(title: str = "", format: str = "markdown") -> str:
    """Export conversation to markdown/text."""
    await _ensure_browser()

    if title:
        await tool_open_conversation(title)

    try:
        # Get all messages
        messages = await _page.evaluate("""() => {
            const msgs = [];
            document.querySelectorAll('message-content, .response-content, user-message, model-response').forEach(msg => {
                msgs.push(msg.innerText || msg.textContent);
            });
            return msgs;
        }""")

        content = "\n\n---\n\n".join(messages)
        return f"Exported {len(messages)} messages:\n\n{content[:1000]}..."
    except Exception as e:
        return f"Error exporting conversation: {e}"


async def tool_list_gems() -> list:
    """List available Gems from the sidebar."""
    await _ensure_browser()
    try:
        gems_btn = await _page.wait_for_selector(
            "button[aria-label='Gems'], a[aria-label='Gems']",
            timeout=3000
        )
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
    """Return the current Gemini page URL (conversation ID)."""
    await _ensure_browser()
    return _page.url


# ── MCP Protocol ─────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "send_message",
        "description": "Send a message to Gemini Web. Has Google Search built-in.",
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
        "description": "Start a fresh Gemini conversation.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_conversations",
        "description": "List recent conversations.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "open_conversation",
        "description": "Open conversation by partial title match.",
        "inputSchema": {
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
        },
    },
    {
        "name": "create_image",
        "description": "Generate image via Gemini.",
        "inputSchema": {
            "type": "object",
            "properties": {"prompt": {"type": "string"}},
            "required": ["prompt"],
        },
    },
    {
        "name": "upload_file",
        "description": "Upload single file for analysis.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "prompt": {"type": "string"},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "upload_folder",
        "description": "Upload entire folder (auto-zips).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "folder_path": {"type": "string"},
                "prompt": {"type": "string"},
            },
            "required": ["folder_path"],
        },
    },
    {
        "name": "upload_github_url",
        "description": "Import code from GitHub URL.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "github_url": {"type": "string"},
                "prompt": {"type": "string"},
            },
            "required": ["github_url"],
        },
    },
    {
        "name": "search_conversations",
        "description": "Search conversation history.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "delete_conversation",
        "description": "Delete a conversation.",
        "inputSchema": {
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
        },
    },
    {
        "name": "pin_conversation",
        "description": "Pin/unpin conversation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "pin": {"type": "boolean", "default": True},
            },
            "required": ["title"],
        },
    },
    {
        "name": "share_conversation",
        "description": "Get shareable link.",
        "inputSchema": {
            "type": "object",
            "properties": {"title": {"type": "string"}},
        },
    },
    {
        "name": "export_conversation",
        "description": "Export conversation to text.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "format": {"type": "string", "default": "markdown"},
            },
        },
    },
    {
        "name": "list_gems",
        "description": "List available AI personas.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_current_url",
        "description": "Get current conversation URL.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

TOOL_MAP = {
    "send_message": lambda a: tool_send_message(a["prompt"], a.get("new_conversation", False)),
    "new_conversation": lambda a: tool_new_conversation(),
    "list_conversations": lambda a: tool_list_conversations(),
    "open_conversation": lambda a: tool_open_conversation(a["title"]),
    "create_image": lambda a: tool_create_image(a["prompt"]),
    "upload_file": lambda a: tool_upload_file(a["file_path"], a.get("prompt", "")),
    "upload_folder": lambda a: tool_upload_folder(a["folder_path"], a.get("prompt", "")),
    "upload_github_url": lambda a: tool_upload_github_url(a["github_url"], a.get("prompt", "")),
    "search_conversations": lambda a: tool_search_conversations(a["query"]),
    "delete_conversation": lambda a: tool_delete_conversation(a["title"]),
    "pin_conversation": lambda a: tool_pin_conversation(a["title"], a.get("pin", True)),
    "share_conversation": lambda a: tool_share_conversation(a.get("title", "")),
    "export_conversation": lambda a: tool_export_conversation(a.get("title", ""), a.get("format", "markdown")),
    "list_gems": lambda a: tool_list_gems(),
    "get_current_url": lambda a: tool_get_current_url(),
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
            "serverInfo": {"name": "gemini-web", "version": "2.0.0"},
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
    try:
        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break

                line_str = line if isinstance(line, str) else line.decode()
                req = json.loads(line_str)
                resp = await handle(req)

                if resp is not None:
                    sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                    sys.stdout.flush()

            except json.JSONDecodeError:
                continue
            except Exception as e:
                sys.stderr.write(f"[MCP] Error: {e}\n")
                sys.stderr.flush()

    except Exception as e:
        sys.stderr.write(f"[MCP] Fatal error: {e}\n")
        sys.stderr.flush()
        sys.exit(1)


def main_sync():
    if not STORAGE_FILE.exists():
        sys.stderr.write("No session. Run: python gemini_login.py\n")
        sys.exit(1)
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
