"""
Web Search Skill — DuckDuckGo (free, no API key required).
Tier: SAFE — pure information retrieval, no side effects.
"""

import logging
from duckclaw.skills.base import BaseSkill, SkillPermission, SkillResult

logger = logging.getLogger(__name__)


class WebSearchSkill(BaseSkill):
    name = "web_search"
    description = "Search the web using DuckDuckGo. Free, no API key needed."
    version = "1.0.0"
    permissions = [SkillPermission.WEB_SEARCH]  # Tier: SAFE

    async def execute(self, action: str, params: dict) -> SkillResult:
        if action == "search":
            return await self._search(params)
        elif action == "news":
            return await self._news(params)
        return SkillResult(success=False, error=f"Unknown action: {action}")

    async def _search(self, params: dict) -> SkillResult:
        query = params.get("query", "").strip()
        if not query:
            return SkillResult(success=False, error="query is required")

        max_results = min(int(params.get("max_results", 5)), 10)

        # SAFE tier: no permission check needed — just inform
        await self._permissions.check(
            action_type="web_search",
            description=f'Web search: "{query}"',
            details={"query": query, "max_results": max_results},
            source=f"skill:{self.name}",
            session_id=self._session_id,
        )

        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                raw = list(ddgs.text(query, max_results=max_results))

            results = [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                }
                for r in raw
            ]

            if not results:
                return SkillResult(success=True, data="No results found.", action_taken=f'Searched: "{query}"')

            formatted = f'Search results for: "{query}"\n\n'
            for i, r in enumerate(results, 1):
                formatted += f"{i}. **{r['title']}**\n"
                formatted += f"   {r['snippet']}\n"
                formatted += f"   {r['url']}\n\n"

            return SkillResult(
                success=True,
                data=formatted,
                action_taken=f'Searched web for "{query}"',
                metadata={"result_count": len(results), "results": results},
            )

        except ImportError:
            return SkillResult(success=False, error="duckduckgo-search not installed. Run: pip install duckduckgo-search")
        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return SkillResult(success=False, error=f"Search failed: {e}")

    async def _news(self, params: dict) -> SkillResult:
        query = params.get("query", "").strip()
        max_results = min(int(params.get("max_results", 5)), 10)

        await self._permissions.check(
            action_type="web_search",
            description=f'News search: "{query}"',
            source=f"skill:{self.name}",
            session_id=self._session_id,
        )

        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                raw = list(ddgs.news(query, max_results=max_results))

            if not raw:
                return SkillResult(success=True, data="No news found.")

            formatted = f'Latest news for: "{query}"\n\n'
            for i, r in enumerate(raw, 1):
                formatted += f"{i}. **{r.get('title', '')}**\n"
                formatted += f"   {r.get('body', '')}\n"
                formatted += f"   Source: {r.get('source', '')} · {r.get('date', '')}\n"
                formatted += f"   {r.get('url', '')}\n\n"

            return SkillResult(success=True, data=formatted, action_taken=f'News search: "{query}"')

        except Exception as e:
            return SkillResult(success=False, error=str(e))
