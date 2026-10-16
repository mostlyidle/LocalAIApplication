"""Web tools for fetching, scraping, and summarizing web content.

Provides URL fetching with BeautifulSoup for content extraction,
designed to run fully locally without any API keys.
"""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse, urlsplit

import httpx
import structlog
from langchain_core.tools import tool

logger = structlog.get_logger(__name__)

# Safety limits
MAX_CONTENT_LENGTH = 500_000  # 500KB max page content
REQUEST_TIMEOUT = 30.0
MAX_URLS_PER_REQUEST = 5
MAX_SEARCH_QUERY_LENGTH = 500
MAX_SEARCH_RESULTS = 8
SEARCH_URL = "https://html.duckduckgo.com/html/"


async def fetch_url(url: str, timeout: float = REQUEST_TIMEOUT) -> dict[str, Any]:
    """Fetch a URL and return raw response info.

    Args:
        url: The URL to fetch.
        timeout: Request timeout in seconds.

    Returns:
        Dict with url, status_code, content_type, text, and headers.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return {"url": url, "error": f"Unsupported scheme: {parsed.scheme}"}

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "LocalAI-WebAgent/1.0"},
        ) as client:
            async with client.stream("GET", url) as resp:
                content = bytearray()
                async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                    remaining = MAX_CONTENT_LENGTH - len(content)
                    content.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        break
            return {
                "url": str(resp.url),
                "status_code": resp.status_code,
                "content_type": resp.headers.get("content-type", ""),
                "text": content.decode(resp.encoding or "utf-8", errors="replace"),
                "headers": dict(resp.headers),
            }
    except httpx.TimeoutException:
        return {"url": url, "error": "Request timed out"}
    except httpx.ConnectError:
        return {"url": url, "error": "Failed to connect"}
    except Exception as exc:
        logger.error("fetch_url_failed", url=url, error=str(exc))
        return {"url": url, "error": str(exc)}


def extract_text_from_html(html: str) -> str:
    """Extract clean text from HTML using BeautifulSoup.

    Removes scripts, styles, nav, footer, and other non-content elements.
    """
    from bs4 import BeautifulSoup
    from trafilatura import extract

    extracted = extract(html, include_comments=False, include_tables=True)
    if extracted and extracted.strip():
        return extracted.strip()

    soup = BeautifulSoup(html, "html.parser")

    # Remove non-content elements
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)

    # Collapse multiple blank lines
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def extract_links(html: str, base_url: str) -> list[dict[str, str]]:
    """Extract links from HTML content.

    Args:
        html: Raw HTML string.
        base_url: Base URL for resolving relative links.

    Returns:
        List of dicts with 'text' and 'url' keys.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        full_url = urljoin(base_url, href)
        text = a_tag.get_text(strip=True)
        if full_url.startswith(("http://", "https://")) and text:
            links.append({"text": text[:200], "url": full_url})
    return links


# ── LangChain tool wrappers ────────────────────────────────────────────


@tool
async def web_fetch_tool(url: str) -> str:
    """Fetch a web page and extract its main text content.

    Retrieves the URL, strips HTML formatting, and returns clean text.
    Useful for reading articles, documentation, or any web page.

    Args:
        url: The full URL to fetch (must start with http:// or https://).

    Returns:
        The extracted text content of the web page.
    """
    result = await fetch_url(url)

    if "error" in result:
        return f"Error fetching {url}: {result['error']}"

    if result["status_code"] != 200:
        return f"HTTP {result['status_code']} error fetching {url}"

    content_type = result.get("content_type", "")
    if "text/html" in content_type or "text/plain" in content_type:
        text = extract_text_from_html(result["text"])
        if not text.strip():
            return "The page was fetched but no meaningful text content was found."
        # Cap for LLM context
        return text[:10000]
    else:
        return f"Non-text content type: {content_type}. Cannot extract text."


@tool
async def web_search_links_tool(url: str) -> str:
    """Fetch a web page and extract all links from it.

    Useful for discovering related pages, navigation, or finding
    specific resources linked from a page.

    Args:
        url: The full URL to fetch and extract links from.

    Returns:
        List of links found on the page with their text labels.
    """
    result = await fetch_url(url)

    if "error" in result:
        return f"Error fetching {url}: {result['error']}"

    links = extract_links(result["text"], result["url"])
    if not links:
        return "No links found on this page."

    lines = [f"Found {len(links)} links:"]
    for link in links[:30]:  # Cap to 30 links
        lines.append(f"  [{link['text']}] -> {link['url']}")

    if len(links) > 30:
        lines.append(f"  ... and {len(links) - 30} more links")

    return "\n".join(lines)


def extract_search_results(html: str) -> list[dict[str, str]]:
    """Extract titles, snippets, and destination URLs from DuckDuckGo HTML results."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for result in soup.select(".result"):
        anchor = result.select_one("a.result__a")
        if anchor is None:
            continue

        href = str(anchor.get("href", ""))
        parsed_href = urlsplit(href)
        if parsed_href.hostname and (
            parsed_href.hostname == "duckduckgo.com"
            or parsed_href.hostname.endswith(".duckduckgo.com")
        ):
            href = parse_qs(parsed_href.query).get("uddg", [""])[0]
        destination = urlparse(href)
        if (
            destination.scheme not in {"http", "https"}
            or not destination.netloc
            or href in seen_urls
        ):
            continue

        snippet = result.select_one(".result__snippet")
        results.append({
            "title": anchor.get_text(" ", strip=True),
            "snippet": snippet.get_text(" ", strip=True) if snippet else "",
            "url": href,
        })
        seen_urls.add(href)
        if len(results) == MAX_SEARCH_RESULTS:
            break

    return results


@tool
async def web_search_tool(query: str) -> str:
    """Search the public web by topic and return result titles, snippets, and source URLs."""
    query = query.strip()
    if not query:
        return "Search query cannot be empty."
    if len(query) > MAX_SEARCH_QUERY_LENGTH:
        return f"Search query is too long. Maximum length is {MAX_SEARCH_QUERY_LENGTH} characters."

    try:
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "LocalAI-WebAgent/1.0"},
        ) as client:
            response = await client.get(SEARCH_URL, params={"q": query})
    except httpx.TimeoutException:
        return "Web search failed: Request timed out."
    except httpx.RequestError as exc:
        logger.warning("web_search_failed", error=type(exc).__name__)
        return "Web search failed: Could not connect to the search service."

    if response.status_code != 200:
        return f"Web search returned HTTP {response.status_code}."

    results = extract_search_results(response.text[:MAX_CONTENT_LENGTH])
    if not results:
        return f"No web results found for: {query}"

    lines = [f"Web search results for: {query}"]
    for item in results:
        lines.extend((
            f"\n[{item['title']}]({item['url']})",
            item["snippet"] or "No summary was provided for this result.",
        ))
    return "\n".join(lines)


@tool
async def web_multi_fetch_tool(urls: list[str]) -> str:
    """Fetch multiple web pages concurrently and extract their text.

    Useful for comparing information from multiple sources.
    Limited to 5 URLs per request.

    Args:
        urls: List of URLs to fetch (max 5).

    Returns:
        Combined text content from all successfully fetched pages.
    """
    if len(urls) > MAX_URLS_PER_REQUEST:
        return f"Too many URLs. Maximum is {MAX_URLS_PER_REQUEST}."

    tasks = [fetch_url(url) for url in urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    parts = []
    for url, result in zip(urls, results):
        if isinstance(result, Exception):
            parts.append(f"--- {url} ---\nError: {result}\n")
            continue

        if "error" in result:
            parts.append(f"--- {url} ---\nError: {result['error']}\n")
            continue

        text = extract_text_from_html(result["text"])
        parts.append(f"--- {url} ---\n{text[:5000]}\n")

    return "\n".join(parts)


# All web tools for agent binding
web_tools = [web_search_tool, web_fetch_tool, web_search_links_tool, web_multi_fetch_tool]
