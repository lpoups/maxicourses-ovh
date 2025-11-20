import os
from typing import Optional
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async


async def make_context(headless: bool = True,
                       proxy: Optional[str] = None,
                       storage_state_path: Optional[str] = None,
                       user_agent: Optional[str] = None,
                       use_stealth: bool = True):
    p = await async_playwright().start()
    use_chrome = os.getenv("USE_CHROME", "0") == "1"
    use_cdp_env = os.getenv("USE_CDP")
    use_cdp = True if use_cdp_env is None else use_cdp_env == "1"
    cdp_url = os.getenv("CDP_URL") or "http://127.0.0.1:9222"
    launch_kwargs = {"headless": headless, "timeout": 60000}
    if proxy:
        launch_kwargs["proxy"] = {"server": proxy}
    if use_chrome:
        launch_kwargs["channel"] = "chrome"
    if use_cdp:
        # Connect to an already running Chrome in remote-debug mode
        try:
            browser = await p.chromium.connect_over_cdp(cdp_url)
        except Exception as exc:
            await p.stop()
            raise RuntimeError(f"Impossible de se connecter à Chrome debug via {cdp_url}: {exc}") from exc
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
    else:
        raise RuntimeError(
            "Exécution sans Chrome remote-debug interdite. Lance Chrome avec ./start_chrome_debug.sh "
            "ou exporte USE_CDP=1."
        )
    page = await context.new_page()
    if use_stealth:
        try:
            await stealth_async(page)
        except Exception:
            pass
    return p, browser, context, page


def state_path_for(site: str, base_dir: Optional[str] = None) -> Optional[str]:
    base = base_dir or os.environ.get("STATE_DIR") or os.path.join(os.path.dirname(__file__), "..", "state")
    path = os.path.abspath(os.path.join(base, f"{site}.json"))
    return path if os.path.exists(path) else None
