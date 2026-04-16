#!/usr/bin/env python3
"""
Gemini Web client via Playwright.
Uso: python src/gemini_cdp.py "sua pergunta aqui"
Requer login prévio via: python gemini-login.py
"""
import asyncio
import sys
from pathlib import Path

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("[GEMINI] Instale: pip install playwright && playwright install chromium")
    sys.exit(1)

STATE_DIR    = Path(__file__).parent.parent / ".goon_state" / "chrome_profile"
STORAGE_FILE = STATE_DIR / "storage_state.json"
CHROME       = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


async def send_message(prompt: str) -> str:
    if not STORAGE_FILE.exists():
        print("[GEMINI] Sessão não encontrada. Execute: python gemini-login.py")
        sys.exit(1)

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(STATE_DIR),
            headless=True,
            executable_path=CHROME,
            args=["--no-sandbox", "--disable-gpu"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        print("[GEMINI] Carregando sessão...")
        await page.goto("https://gemini.google.com/app", timeout=30000)
        # domcontentloaded is enough — Gemini never reaches networkidle
        await page.wait_for_load_state("domcontentloaded", timeout=15000)

        if "accounts.google.com" in page.url:
            print("[GEMINI] Sessão expirada. Execute: python gemini-login.py")
            await ctx.close()
            sys.exit(1)

        # Dump available input selectors for debugging
        selectors = await page.evaluate("""() => {
            const candidates = [
                'rich-textarea div[contenteditable]',
                'div[contenteditable="true"]',
                'textarea',
                '[data-placeholder]',
                'input-area textarea',
                'input-area div[contenteditable]',
            ];
            return candidates.map(s => ({
                selector: s,
                count: document.querySelectorAll(s).length
            }));
        }""")
        print("[GEMINI] Seletores disponíveis:", selectors)

        # Find first working input selector
        input_sel = None
        for s in ['rich-textarea div[contenteditable="true"]',
                  'div[contenteditable="true"]',
                  'input-area div[contenteditable]',
                  'textarea']:
            try:
                el = await page.wait_for_selector(s, timeout=5000)
                if el:
                    input_sel = s
                    print(f"[GEMINI] Usando seletor: {s}")
                    break
            except Exception:
                continue

        if not input_sel:
            print("[GEMINI] Nenhum seletor de input encontrado.")
            await ctx.close()
            sys.exit(1)

        print(f"[GEMINI] Enviando: {prompt[:80]}...")
        await page.click(input_sel)
        await page.keyboard.type(prompt)
        await page.keyboard.press("Enter")

        # Wait for stop button to appear then disappear
        try:
            await page.wait_for_selector(
                "button[aria-label='Stop response'], button[aria-label='Parar resposta']",
                timeout=10000)
            await page.wait_for_selector(
                "button[aria-label='Stop response'], button[aria-label='Parar resposta']",
                state="hidden", timeout=120000)
        except Exception:
            # Fallback: just wait a bit
            await asyncio.sleep(8)

        # Try multiple response selectors
        text = ""
        for sel in ["model-response .response-content",
                    "message-content .markdown",
                    ".response-container-content",
                    "model-response"]:
            els = await page.query_selector_all(sel)
            if els:
                text = await els[-1].inner_text()
                print(f"[GEMINI] Resposta (via {sel}):")
                break

        if text:
            print(text)
        else:
            print("[GEMINI] Não foi possível extrair resposta.")

        await ctx.close()
        return text


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python src/gemini_cdp.py \"sua pergunta\"")
        sys.exit(1)
    asyncio.run(send_message(" ".join(sys.argv[1:])))
