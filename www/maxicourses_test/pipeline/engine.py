import os
from typing import Optional
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async


async def make_context(headless: bool = True,
                       proxy: Optional[str] = None,
                       residential_proxy: Optional[str] = None,
                       storage_state_path: Optional[str] = None,
                       user_agent: Optional[str] = None):
    p = await async_playwright().start()
    use_chrome = os.getenv("USE_CHROME", "0") == "1"
    use_cdp = os.getenv("USE_CDP", "0") == "1"
    use_xvfb = os.getenv("USE_XVFB", "0") == "1"
    cdp_url = os.getenv("CDP_URL") or "http://127.0.0.1:9222"
    
    # Force headed mode if using Xvfb
    is_headless = headless and not use_xvfb
    
    launch_kwargs = {
        "headless": is_headless,
        "timeout": 60000,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-infobars",
            "--window-size=1920,1080",
            "--disable-dev-shm-usage",
            "--disable-extensions",
            "--disable-gpu",
        ]
    }
    if residential_proxy:
        launch_kwargs["proxy"] = {"server": residential_proxy}
    elif proxy:
        launch_kwargs["proxy"] = {"server": proxy}
    if use_chrome:
        launch_kwargs["channel"] = "chrome"
    if use_cdp:
        # Connect to an already running Chrome/Chromium (remote debugging)
        browser = await p.chromium.connect_over_cdp(cdp_url)
        # Persistent context when using CDP; reuse first context if any
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        setattr(browser, "_is_cdp", True)
        setattr(context, "_is_cdp", True)
    else:
        browser = await p.chromium.launch(**launch_kwargs)
        context = await browser.new_context(
            storage_state=storage_state_path,
            user_agent=user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="fr-FR",
            timezone_id="Europe/Paris",
        )
        try:
            await context.grant_permissions(["geolocation"])
            await context.set_geolocation({"latitude": 44.8378, "longitude": -0.5792})  # Bordeaux
        except Exception:
            pass
        setattr(browser, "_is_cdp", False)
        setattr(context, "_is_cdp", False)

    if use_cdp and context.pages:
        page = context.pages[0]
    else:
        page = await context.new_page()
    setattr(page, "_is_cdp", use_cdp)
    try:
        await stealth_async(page)
    except Exception:
        pass
    return p, browser, context, page


def state_path_for(site: str, base_dir: Optional[str] = None) -> Optional[str]:
    base = base_dir or os.environ.get("STATE_DIR") or os.path.join(os.path.dirname(__file__), "..", "state")
    path = os.path.abspath(os.path.join(base, f"{site}.json"))
    return path if os.path.exists(path) else None
