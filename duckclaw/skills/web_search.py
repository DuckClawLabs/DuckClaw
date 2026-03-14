"""
Web Search Skill — DuckDuckGo (free, no API key required).
Tier: SAFE — pure information retrieval, no side effects.
"""

import logging
from duckclaw.skills.base import BaseSkill, SkillPermission, SkillResult
from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)


class WebSearchSkill(BaseSkill):
    name = "web_search"
    description = "Search the web using DuckDuckGo. Free, no API key needed."
    version = "1.0.0"
    permissions = [SkillPermission.WEB_SEARCH]  # Tier: SAFE

    async def execute(self, action: str, params: dict) -> SkillResult:
    
        logger.warning(f"Unknown action '{action}' for skill '{params}', defaulting to 'search'")
        if action == "search":
            return await self._search(params)
        elif action == "news":
            return await self._news(params)
    
        # default to search if unknown action
        return await self._search(params)

    async def _search(self, params: dict) -> SkillResult:

        logger.info(f"WebSearchSkill._search called with params: {params}")

        query = params.get("query", "").strip()
        if not query:
            return SkillResult(success=False, error="query is required")

        max_results = min(int(params.get("max_results", 5)), 10)

        await self._permissions.check(
            action_type="web_search",
            description=f'Web search: "{query}"',
            details={"query": query, "max_results": max_results},
            source=f"skill:{self.name}",
            session_id=self._session_id,
        )

        retries = 3
        delay = 2

        try:

            raw = None

            for attempt in range(retries):

                try:

                    with DDGS(timeout=20) as ddgs:
                        raw = list(
                            ddgs.text(
                                query,
                                max_results=max_results,
                                backend="lite"
                            )
                        )

                    if raw:
                        break

                except Exception as e:

                    if "ratelimit" in str(e).lower():

                        sleep_time = delay * (attempt + 1) + random.uniform(0.5, 1.5)
                        logger.warning(f"DuckDuckGo rate limited. Retrying in {sleep_time:.2f}s")

                        time.sleep(sleep_time)
                        continue

                    raise

            if raw is None:
                return SkillResult(success=False, error="Search failed due to repeated rate limits")

            results = [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                }
                for r in raw
            ]

            if not results:
                return SkillResult(
                    success=True,
                    data="No results found.",
                    action_taken=f'Searched: "{query}"'
                )

            formatted = f'Search results for: "{query}"\n\n'

            for i, r in enumerate(results, 1):
                formatted += f"{i}. **{r['title']}**\n"
                formatted += f"   {r['snippet']}\n"
                formatted += f"   {r['url']}\n\n"

            return SkillResult(
                success=True,
                data=formatted,
                action_taken=f'Searched web for "{query}"',
                metadata={
                    "result_count": len(results),
                    "results": results
                },
            )

        except ImportError:

            return SkillResult(
                success=False,
                error="duckduckgo-search not installed. Run: pip install duckduckgo-search"
            )

        except Exception as e:

            logger.error(f"Web search failed: {e}")

            return SkillResult(
                success=False,
                error=f"Search failed: {e}"
            )

    async def _news(self, params: dict) -> SkillResult:
        logger.info(f"WebSearchSkill._news called with params: {params}")
        query = params.get("query", "").strip()
        max_results = min(int(params.get("max_results", 5)), 10)

        await self._permissions.check(
            action_type="web_search",
            description=f'News search: "{query}"',
            source=f"skill:{self.name}",
            session_id=self._session_id,
        )
        logger.info(f"Permission check passed for news search with query: '{query}'")
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                raw = list(ddgs.news(query, max_results=max_results))
                logger.info(f"Raw news search results for query '{query}': {raw}")

            if not raw:
                return SkillResult(success=True, data="No news found.")

            formatted = f'Latest news for: "{query}"\n\n'
            logger.info(f"Formatting news results for query '{query}'")
            for i, r in enumerate(raw, 1):
                formatted += f"{i}. **{r.get('title', '')}**\n"
                formatted += f"   {r.get('body', '')}\n"
                formatted += f"   Source: {r.get('source', '')} · {r.get('date', '')}\n"
                formatted += f"   {r.get('url', '')}\n\n"

            logger.info(f"Formatted news results text for query '{query}': {formatted}")
            return SkillResult(success=True, data=formatted, action_taken=f'News search: "{query}"')

        except Exception as e:
            return SkillResult(success=False, error=str(e))
