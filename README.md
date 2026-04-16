# gemini-web-mcp

MCP server for Gemini Web — no API key required. Uses your browser session via Playwright.

## Tools

| Tool | Description |
|---|---|
| `send_message` | Send a message and get Gemini's response (Google Search built-in) |
| `new_conversation` | Start a fresh conversation |
| `list_conversations` | List recent conversations from sidebar |
| `open_conversation` | Open a conversation by partial title match |
| `create_image` | Generate an image from a text prompt |
| `upload_file` | Upload a local file and optionally ask about it |
| `list_gems` | List available Gems (custom AI personas) |
| `get_current_url` | Get current conversation URL |

## Setup

### 1. Install dependencies

```bash
pip install playwright websocket-client
playwright install chromium
```

### 2. Login (one-time)

```bash
python gemini_login.py
```

Chrome opens, you log in, session is saved automatically when `SAPISID` cookie appears.

### 3. Register MCP server

**Claude Code:**
```bash
claude mcp add --scope user gemini-web python /path/to/gemini_mcp.py
```

**OpenCode:**
```json
// ~/.config/opencode/opencode.json
{
  "mcp": {
    "gemini-web": {
      "type": "local",
      "command": ["python", "/path/to/gemini_mcp.py"]
    }
  }
}
```

## How it works

- `gemini_login.py` — launches Chrome via subprocess with `--remote-debugging-port`, polls CDP WebSocket until `SAPISID` cookie appears, saves session as `storage_state.json`
- `gemini_playwright.py` — Playwright client that loads the saved session and interacts with Gemini Web UI
- `gemini_mcp.py` — MCP server (JSON-RPC 2.0 over stdio) that exposes Playwright tools

Session is stored in `.goon_state/chrome_profile/storage_state.json` (gitignored).

## License

MIT
