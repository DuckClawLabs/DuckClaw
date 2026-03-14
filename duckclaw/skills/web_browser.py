"""
DuckClaw Web Browser Skill — Playwright-based web agent.

Actions:
- navigate    : Load a URL, return page title + text content (NOTIFY)
- click       : Click an element by CSS selector or visible text (ASK)
- fill_form   : Fill form fields — optionally submit (ASK)
- screenshot  : Screenshot of current page (SAFE — no local screen involved)
- extract_text: Pull structured text / links from a page (NOTIFY)
- search      : DuckDuckGo search → return result list (SAFE)

Security:
- URL blocklist: file://, localhost, private IPs blocked via is_safe_url()
- Form submission requires ASK-tier approval every time
- Navigation is NOTIFY tier (informational, no persistent side effects)
- Each session uses an isolated browser context (no shared cookies/storage)
- Max page content returned: 50K chars
- Timeout: 30 seconds per action
"""

import logging
import re
from typing import Any, Optional, TYPE_CHECKING

from duckclaw.skills.base import BaseSkill, SkillPermission, SkillResult
from duckclaw.security.context_isolation import is_safe_url

if TYPE_CHECKING:
    from duckclaw.permissions.engine import PermissionEngine

logger = logging.getLogger(__name__)

MAX_CONTENT_CHARS = 50_000
ACTION_TIMEOUT_MS = 30_000


class WebBrowserSkill(BaseSkill):
    """Playwright-powered web browsing with per-action permission checks."""

    name = "web_browser"
    description = (
        "Browse websites, click elements, fill forms, and extract page content. "
        "Navigation is automatic; form submission requires your approval."
    )
    version = "1.0.0"
    permissions = [
        SkillPermission.WEB_BROWSE,
        SkillPermission.WEB_SUBMIT,
    ]
    network_allowed = True

    def __init__(self, permission_engine: "PermissionEngine"):
        super().__init__(permission_engine)
        self._browser = None
        self._context = None
        self._page = None
        self._current_url: Optional[str] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def _ensure_browser(self):
        """Lazy-init Playwright browser."""
        if self._browser is None:
            try:
                from playwright.async_api import async_playwright
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox"],
                )
                logger.info("Chromium browser launched")
                self._context = await self._browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    ),
                    java_script_enabled=True,
                )
                logger.info("Browser context created with isolated session")
                self._page = await self._context.new_page()
                self._page.set_default_timeout(ACTION_TIMEOUT_MS)
                logger.info("New page created with default timeout set")
            except ImportError:
                raise RuntimeError(
                    "Playwright not installed. Run: pip install playwright && playwright install chromium"
                )
        
        logger.info("Playwright browser initialized")

    async def _close_browser(self):
        if self._browser:
            await self._browser.close()
            await self._playwright.stop()
            self._browser = None
            self._context = None
            self._page = None
        
        logger.info("Playwright browser closed")

    # ── Entry point ────────────────────────────────────────────────────────────

    async def execute(self, action: str, params: dict) -> SkillResult:
        handlers = {
            "navigate":     self._navigate,
            "click":        self._click,
            "fill_form":    self._fill_form,
            # "screenshot":   self._screenshot, # we will think about multi-skill
            "extract_text": self._extract_text,
            "search":       self._search,
        }
        try:
            logger.info(f"WebBrowserSkill executing action: {action} with params: {params}")
            return await handlers.get(action, self._navigate)(params)
        except Exception as e:
            logger.exception(f"WebBrowserSkill.{action} failed")
            return SkillResult(success=False, error=str(e))

    # ── Actions ────────────────────────────────────────────────────────────────

    async def _navigate(self, params: dict) -> SkillResult:
        logger.info(f"Navigate action called with params: {params}")
        url = params.get("url", "").strip()
        if not url:
            logger.warning("Navigate action missing 'url' parameter")
            return SkillResult(success=False, error="'url' parameter required")
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        logger.info(f"Attempting to navigate to URL: {url}")
        if not is_safe_url(url):
            logger.warning(f"Blocked navigation to unsafe URL: {url}")
            return SkillResult(
                success=False,
                error=f"URL blocked by security policy: {url}"
            )

        allowed = await self._check(
            action_type="web.browse",
            description=f"Navigate to {url}",
            details={"url": url},
            reversible=True,
            risk_level="low",
        )
        logger.info(f"Permission check for navigating to {url} returned: {allowed}")
        if not allowed:
            return SkillResult(success=False, error="Navigation denied by user.")

        await self._ensure_browser()
        response = await self._page.goto(url, wait_until="domcontentloaded")
        logger.info(f"Navigation to {url} completed with status: {response.status if response else 'no response'}")
        self._current_url = self._page.url

        title = await self._page.title()
        content = await self._extract_readable_text()
        logger.info(f"Extracted title and content from {self._current_url} (title: {title}, content length: {len(content)})")

        sr = SkillResult(
            success=True,
            data={
                "url": self._current_url,
                "title": title,
                "content": content[:MAX_CONTENT_CHARS],
                "status_code": response.status if response else None,
            },
            action_taken=f"Navigated to {url}",
            metadata={"url": self._current_url, "title": title},
        )
        logger.info(f"Navigate action returning SkillResult: {sr}")
        return sr

    async def _click(self, params: dict) -> SkillResult:
        logger.info(f"Click action called with params: {params}")
        selector = params.get("selector", "").strip()
        text = params.get("text", "").strip()

        if not selector and not text:
            logger.warning("Click action missing 'selector' and 'text' parameters")
            return SkillResult(success=False, error="'selector' or 'text' required")
        if not self._page:
            logger.warning("Click action called but no page loaded")
            return SkillResult(success=False, error="No page loaded. Call navigate first.")

        target_desc = f"'{text}'" if text else f"selector '{selector}'"
        allowed = await self._check(
            action_type="web.click",
            description=f"Click {target_desc} on {self._current_url or 'page'}",
            details={"selector": selector, "text": text, "url": self._current_url},
            reversible=False,
            risk_level="medium",
        )
        logger.info(f"Permission check for clicking {target_desc} returned: {allowed}")
        if not allowed:
            return SkillResult(success=False, error="Click denied by user.")

        if text:
            await self._page.get_by_text(text, exact=False).first.click()
        else:
            await self._page.click(selector)

        logger.info(f"Clicked {target_desc}, waiting for page to load")
        await self._page.wait_for_load_state("domcontentloaded")
        self._current_url = self._page.url
        title = await self._page.title()
        logger.info(f"After click, navigated to {self._current_url} with title: {title}")
        click_sr = SkillResult(
            success=True,
            data={"url": self._current_url, "title": title},
            action_taken=f"Clicked {target_desc}",
        )
        logger.info(f"Click action returning SkillResult: {click_sr}")
        return click_sr

    async def _fill_form(self, params: dict) -> SkillResult:
        """Fill form fields. fields = [{"selector": "...", "value": "..."}]"""
        logger.info(f"Fill form action called with params: {params}")
        fields: list[dict] = params.get("fields", [])
        submit: bool = params.get("submit", False)

        if not fields:
            logger.warning("Fill form action missing 'fields' parameter")
            return SkillResult(success=False, error="'fields' list required")
        if not self._page:
            logger.warning("Fill form action called but no page loaded")
            return SkillResult(success=False, error="No page loaded. Call navigate first.")

        field_summary = ", ".join(
            f"{f.get('selector', '?')}={f.get('value', '')[:20]}" for f in fields
        )
        risk = "high" if submit else "medium"
        desc = (
            f"Fill form on {self._current_url or 'page'} ({field_summary})"
            + (" and submit" if submit else "")
        )
        logger.info(f"Requesting permission to {desc} with risk level: {risk}")

        allowed = await self._check(
            action_type="web.submit" if submit else "web.browse",
            description=desc,
            details={"fields": fields, "submit": submit, "url": self._current_url},
            reversible=not submit,
            risk_level=risk,
        )
        logger.info(f"Permission check for filling form returned: {allowed}")
        if not allowed:
            return SkillResult(success=False, error="Form fill denied by user.")

        for field in fields:
            selector = field.get("selector", "")
            value = field.get("value", "")
            clear_first = field.get("clear", True)
            if not selector:
                continue
            if clear_first:
                await self._page.fill(selector, value)
            else:
                await self._page.type(selector, value)

        logger.info(f"Filled form fields: {field_summary}")
        if submit:
            await self._page.keyboard.press("Enter")
            await self._page.wait_for_load_state("domcontentloaded")
            self._current_url = self._page.url

        logger.info(f"After filling form{' and submitting' if submit else ''}, current URL: {self._current_url}")
        fill_form_sr = SkillResult(
            success=True,
            data={"submitted": submit, "url": self._current_url},
            action_taken=desc,
        )
        logger.info(f"Fill form action returning SkillResult: {fill_form_sr}")
        return fill_form_sr

    # async def _screenshot(self, params: dict) -> SkillResult:
    #     """Capture current page as base64 JPEG."""
    #     if not self._page:
    #         return SkillResult(success=False, error="No page loaded. Call navigate first.")

    #     import base64
    #     png_bytes = await self._page.screenshot(full_page=params.get("full_page", False))

    #     # Compress via Pillow
    #     try:
    #         from PIL import Image
    #         import io
    #         img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    #         buf = io.BytesIO()
    #         img.save(buf, format="JPEG", quality=85)
    #         jpeg_bytes = buf.getvalue()
    #     except ImportError:
    #         jpeg_bytes = png_bytes

    #     b64 = base64.b64encode(jpeg_bytes).decode()
    #     title = await self._page.title()

    #     return SkillResult(
    #         success=True,
    #         data={
    #             "image_base64": b64,
    #             "url": self._current_url,
    #             "title": title,
    #             "format": "jpeg",
    #         },
    #         action_taken=f"Captured screenshot of {self._current_url}",
    #         metadata={"size_bytes": len(jpeg_bytes)},
    #     )

    async def _extract_text(self, params: dict) -> SkillResult:
        """Extract readable text and links from current page."""
        logger.info(f"Extract text action called with params: {params}")
        if not self._page:
            return SkillResult(success=False, error="No page loaded. Call navigate first.")

        content = await self._extract_readable_text()
        links = await self._extract_links(max_links=params.get("max_links", 20))
        title = await self._page.title()
        logger.info(f"Extracted text and links from {self._current_url} (content length: {len(content)}, links found: {len(links)})")

        text_sr = SkillResult(
            success=True,
            data={
                "url": self._current_url,
                "title": title,
                "content": content[:MAX_CONTENT_CHARS],
                "links": links,
            },
            action_taken=f"Extracted text from {self._current_url}",
        )
        logger.info(f"Extract text action returning SkillResult: {text_sr}")
        return text_sr

    async def _search(self, params: dict) -> SkillResult:
        """Search DuckDuckGo and return result list without navigating."""
        query = params.get("query", "").strip()
        max_results = min(params.get("max_results", 8), 20)
        logger.info(f"Search action called with query: '{query}' and max_results: {max_results}")
        if not query:
            return SkillResult(success=False, error="'query' parameter required")

        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
            logger.info(f"Search for '{query}' returned {len(results)} results")
            search_sr = SkillResult(
                success=True,
                data=results,
                action_taken=f"Searched for: {query}",
                metadata={"query": query, "result_count": len(results)},
            )
            logger.info(f"Search action returning SkillResult: {search_sr}")
            return search_sr
        except Exception as e:
            logger.error(f"Search failed for query '{query}': {e}")
            return SkillResult(success=False, error=f"Search failed: {e}")

    # ── Helpers ────────────────────────────────────────────────────────────────

    async def _extract_readable_text(self) -> str:
        """Extract clean body text — strips scripts, styles, nav boilerplate."""
        try:
            text = await self._page.evaluate("""() => {
                const clone = document.body.cloneNode(true);
                ['script','style','nav','header','footer','aside'].forEach(tag => {
                    clone.querySelectorAll(tag).forEach(el => el.remove());
                });
                return clone.innerText || clone.textContent || '';
            }""")
            # Collapse whitespace
            text = re.sub(r'\n{3,}', '\n\n', text.strip())
            logger.info(f"Extracted readable text of length {len(text)} from {self._current_url}")
            return text
        except Exception:
            return ""

    async def _extract_links(self, max_links: int = 20) -> list[dict]:
        try:
            links = await self._page.evaluate(f"""() => {{
                const anchors = Array.from(document.querySelectorAll('a[href]'));
                return anchors.slice(0, {max_links}).map(a => ({{
                    text: a.innerText.trim().slice(0, 100),
                    href: a.href,
                }})).filter(l => l.href.startsWith('http'));
            }}""")
            logger.info(f"Extracted {len(links)} links from {self._current_url}")
            return links
        except Exception:
            logger.error(f"Failed to extract links from {self._current_url}")
            return []
