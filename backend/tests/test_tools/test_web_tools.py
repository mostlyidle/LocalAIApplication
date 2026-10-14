"""Tests for web tools — URL fetching, text extraction, link extraction, and LangChain tools.

Targets app/tools/web_tools.py for 23% → 80%+ coverage.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.tools.web_tools import (
    MAX_CONTENT_LENGTH,
    MAX_URLS_PER_REQUEST,
    extract_links,
    extract_text_from_html,
    fetch_url,
    web_fetch_tool,
    web_multi_fetch_tool,
    web_search_links_tool,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


# =============================================================================
# extract_text_from_html (pure function)
# =============================================================================


class TestExtractTextFromHtml:
    """Tests for the HTML text extraction utility."""

    def test_article_excludes_navigation(self) -> None:
        paragraph = "Local models process private documents without uploading their contents. "
        html = f"<nav>Subscribe Buy Subscribe</nav><article><h1>Local AI</h1><p>{paragraph * 8}</p></article><footer>Cookie preferences</footer>"
        result = extract_text_from_html(html)
        assert "private documents" in result
        assert "Subscribe" not in result
        assert "Cookie preferences" not in result

    def test_sparse_page_falls_back(self) -> None:
        with patch("trafilatura.extract", return_value=None):
            assert extract_text_from_html("<p>Short useful answer</p>") == "Short useful answer"

    def test_basic_paragraph(self):
        """Extracts text from a simple HTML paragraph."""
        html = "<html><body><p>Hello World</p></body></html>"
        result = extract_text_from_html(html)
        assert "Hello World" in result

    def test_removes_scripts_and_styles(self):
        """Script and style elements are stripped."""
        html = """
        <html>
        <head><style>body { color: red; }</style></head>
        <body>
        <p>Good content</p>
        <script>alert('xss');</script>
        </body>
        </html>
        """
        result = extract_text_from_html(html)
        assert "Good content" in result
        assert "alert" not in result
        assert "color: red" not in result

    def test_removes_nav_footer_header_aside(self):
        """Navigation and structural elements are stripped."""
        html = """
        <nav>Menu</nav>
        <header>Header</header>
        <main><p>Main content</p></main>
        <aside>Sidebar</aside>
        <footer>Footer</footer>
        """
        result = extract_text_from_html(html)
        assert "Main content" in result
        assert "Menu" not in result
        assert "Footer" not in result

    def test_collapses_blank_lines(self):
        """Multiple blank lines are collapsed."""
        html = "<p>Line 1</p><br><br><br><p>Line 2</p>"
        result = extract_text_from_html(html)
        lines = result.strip().splitlines()
        assert all(line.strip() for line in lines)

    def test_empty_html(self):
        """Empty HTML returns empty string."""
        assert extract_text_from_html("") == ""


# =============================================================================
# extract_links (pure function)
# =============================================================================


class TestExtractLinks:
    """Tests for HTML link extraction."""

    def test_extracts_absolute_links(self):
        """Absolute URLs are extracted with their text."""
        html = '<a href="https://example.com">Example</a>'
        result = extract_links(html, "https://base.com")
        assert len(result) == 1
        assert result[0]["text"] == "Example"
        assert result[0]["url"] == "https://example.com"

    def test_resolves_relative_links(self):
        """Relative URLs are resolved against base_url."""
        html = '<a href="/about">About</a>'
        result = extract_links(html, "https://example.com")
        assert result[0]["url"] == "https://example.com/about"

    def test_skips_empty_text_links(self):
        """Links with no text are skipped."""
        html = '<a href="https://example.com"></a>'
        result = extract_links(html, "https://example.com")
        assert len(result) == 0

    def test_skips_non_http_links(self):
        """mailto, javascript, etc. links are skipped."""
        html = """
        <a href="mailto:nobody@example.invalid">Email</a>
        <a href="javascript:void(0)">Click</a>
        <a href="https://good.com">Good</a>
        """
        result = extract_links(html, "https://base.com")
        assert len(result) == 1
        assert result[0]["url"] == "https://good.com"

    def test_truncates_long_text(self):
        """Link text longer than 200 chars is truncated."""
        long_text = "x" * 300
        html = f'<a href="https://example.com">{long_text}</a>'
        result = extract_links(html, "https://base.com")
        assert len(result[0]["text"]) == 200

    def test_multiple_links(self):
        """Multiple links are all extracted."""
        html = """
        <a href="/page1">Page 1</a>
        <a href="/page2">Page 2</a>
        <a href="/page3">Page 3</a>
        """
        result = extract_links(html, "https://example.com")
        assert len(result) == 3


# =============================================================================
# fetch_url
# =============================================================================


class TestFetchUrl:
    """Tests for the fetch_url async function."""

    @staticmethod
    def _mock_stream_client(response: MagicMock) -> MagicMock:
        stream_context = MagicMock()
        stream_context.__aenter__ = AsyncMock(return_value=response)
        stream_context.__aexit__ = AsyncMock(return_value=None)
        mock_client = MagicMock()
        mock_client.stream = MagicMock(return_value=stream_context)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        return mock_client

    async def test_successful_fetch(self):
        """Successful HTTP GET returns url, status, content, headers."""
        mock_response = MagicMock()
        mock_response.url = "https://example.com"
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_response.encoding = "utf-8"
        mock_response.aiter_bytes = lambda chunk_size: self._chunks(
            b"<html><body>Hello</body></html>"
        )

        mock_client = self._mock_stream_client(mock_response)

        with patch("app.tools.web_tools.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_url("https://example.com")

        assert result["status_code"] == 200
        assert "Hello" in result["text"]

    async def test_timeout_error(self) -> None:
        """Timeout returns error dict, not exception."""
        mock_client = self._mock_stream_client(MagicMock())
        mock_client.stream.return_value.__aenter__.side_effect = httpx.TimeoutException(
            "timed out"
        )

        with patch("app.tools.web_tools.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_url("https://slow.com")

        assert "error" in result
        assert "timed out" in result["error"].lower()

    async def test_connect_error(self):
        """Connection error returns error dict."""
        mock_client = self._mock_stream_client(MagicMock())
        mock_client.stream.return_value.__aenter__.side_effect = httpx.ConnectError("refused")

        with patch("app.tools.web_tools.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_url("https://down.com")

        assert "error" in result
        assert "connect" in result["error"].lower()

    async def test_unsupported_scheme(self):
        """Non-HTTP/HTTPS scheme returns error."""
        result = await fetch_url("ftp://files.example.com/data")
        assert "error" in result
        assert "Unsupported scheme" in result["error"]

    async def test_generic_exception(self):
        """Unexpected exceptions are caught gracefully."""
        mock_client = self._mock_stream_client(MagicMock())
        mock_client.stream.return_value.__aenter__.side_effect = RuntimeError("unexpected")

        with patch("app.tools.web_tools.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_url("https://broken.com")

        assert "error" in result

    async def test_content_truncation(self):
        """Content exceeding MAX_CONTENT_LENGTH is truncated."""
        mock_response = MagicMock()
        mock_response.url = "https://big.com"
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_response.encoding = "utf-8"
        yielded_chunks: list[bytes] = []

        async def chunks(chunk_size: int) -> AsyncIterator[bytes]:
            for content in (b"x" * MAX_CONTENT_LENGTH, b"excess" * 1000):
                yielded_chunks.append(content)
                yield content

        mock_response.aiter_bytes = chunks

        mock_client = self._mock_stream_client(mock_response)

        with patch("app.tools.web_tools.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_url("https://big.com")

        assert len(result["text"]) == MAX_CONTENT_LENGTH
        assert len(yielded_chunks) == 2

    @staticmethod
    async def _chunks(content: bytes) -> AsyncIterator[bytes]:
        yield content


# =============================================================================
# web_fetch_tool (LangChain tool)
# =============================================================================


class TestWebFetchTool:
    """Tests for the web_fetch_tool LangChain wrapper."""

    async def test_returns_text_on_success(self):
        """Successful HTML fetch returns extracted text."""
        html = "<html><body><p>Important info</p></body></html>"
        with patch(
            "app.tools.web_tools.fetch_url",
            new_callable=AsyncMock,
            return_value={
                "url": "https://example.com",
                "status_code": 200,
                "content_type": "text/html; charset=utf-8",
                "text": html,
                "headers": {},
            },
        ):
            result = await web_fetch_tool.ainvoke({"url": "https://example.com"})
        assert "Important info" in result

    async def test_returns_error_message_on_fetch_error(self):
        """Fetch error returns user-friendly error string."""
        with patch(
            "app.tools.web_tools.fetch_url",
            new_callable=AsyncMock,
            return_value={"url": "https://bad.com", "error": "Connection refused"},
        ):
            result = await web_fetch_tool.ainvoke({"url": "https://bad.com"})
        assert "Error" in result
        assert "Connection refused" in result

    async def test_returns_error_on_non_200(self):
        """Non-200 status returns HTTP error message."""
        with patch(
            "app.tools.web_tools.fetch_url",
            new_callable=AsyncMock,
            return_value={
                "url": "https://example.com",
                "status_code": 404,
                "content_type": "text/html",
                "text": "",
                "headers": {},
            },
        ):
            result = await web_fetch_tool.ainvoke({"url": "https://example.com"})
        assert "404" in result

    async def test_handles_non_text_content(self):
        """Non-text content type returns informational message."""
        with patch(
            "app.tools.web_tools.fetch_url",
            new_callable=AsyncMock,
            return_value={
                "url": "https://example.com/file.zip",
                "status_code": 200,
                "content_type": "application/zip",
                "text": "",
                "headers": {},
            },
        ):
            result = await web_fetch_tool.ainvoke({"url": "https://example.com/file.zip"})
        assert "Non-text content" in result

    async def test_handles_empty_page(self):
        """Page with no meaningful text returns appropriate message."""
        with patch(
            "app.tools.web_tools.fetch_url",
            new_callable=AsyncMock,
            return_value={
                "url": "https://example.com",
                "status_code": 200,
                "content_type": "text/html",
                "text": "<html><body><script>only js</script></body></html>",
                "headers": {},
            },
        ):
            result = await web_fetch_tool.ainvoke({"url": "https://example.com"})
        assert "no meaningful text" in result.lower()

    async def test_caps_output_at_10000(self):
        """Output is capped at 10000 characters."""
        big_content = "<p>" + "word " * 3000 + "</p>"
        with patch(
            "app.tools.web_tools.fetch_url",
            new_callable=AsyncMock,
            return_value={
                "url": "https://big.com",
                "status_code": 200,
                "content_type": "text/html",
                "text": big_content,
                "headers": {},
            },
        ):
            result = await web_fetch_tool.ainvoke({"url": "https://big.com"})
        assert len(result) <= 10000


# =============================================================================
# web_search_links_tool
# =============================================================================


class TestWebSearchLinksTool:
    """Tests for the web_search_links_tool."""

    async def test_returns_links(self):
        """Successful fetch returns formatted link list."""
        html = '<a href="https://a.com">Link A</a><a href="https://b.com">Link B</a>'
        with patch(
            "app.tools.web_tools.fetch_url",
            new_callable=AsyncMock,
            return_value={
                "url": "https://example.com",
                "status_code": 200,
                "text": html,
                "headers": {},
            },
        ):
            result = await web_search_links_tool.ainvoke({"url": "https://example.com"})
        assert "Link A" in result
        assert "Link B" in result
        assert "Found 2 links" in result

    async def test_returns_error_on_failure(self):
        """Fetch error returns error message."""
        with patch(
            "app.tools.web_tools.fetch_url",
            new_callable=AsyncMock,
            return_value={"url": "https://bad.com", "error": "timeout"},
        ):
            result = await web_search_links_tool.ainvoke({"url": "https://bad.com"})
        assert "Error" in result

    async def test_no_links_message(self):
        """Page with no links returns appropriate message."""
        with patch(
            "app.tools.web_tools.fetch_url",
            new_callable=AsyncMock,
            return_value={
                "url": "https://example.com",
                "status_code": 200,
                "text": "<p>No links here</p>",
                "headers": {},
            },
        ):
            result = await web_search_links_tool.ainvoke({"url": "https://example.com"})
        assert "No links found" in result


# =============================================================================
# web_multi_fetch_tool
# =============================================================================


class TestWebMultiFetchTool:
    """Tests for the web_multi_fetch_tool."""

    async def test_fetches_multiple_urls(self):
        """Multiple URLs are fetched and combined."""

        async def mock_fetch(url: str, **kwargs) -> dict:
            return {
                "url": url,
                "status_code": 200,
                "text": f"<p>Content from {url}</p>",
                "headers": {},
            }

        with patch("app.tools.web_tools.fetch_url", side_effect=mock_fetch):
            result = await web_multi_fetch_tool.ainvoke(
                {"urls": ["https://a.com", "https://b.com"]}
            )
        assert "Content from https://a.com" in result
        assert "Content from https://b.com" in result

    async def test_rejects_too_many_urls(self):
        """More than MAX_URLS_PER_REQUEST URLs is rejected."""
        urls = [f"https://site{i}.com" for i in range(MAX_URLS_PER_REQUEST + 1)]
        result = await web_multi_fetch_tool.ainvoke({"urls": urls})
        assert "Too many URLs" in result

    async def test_handles_mixed_success_and_failure(self):
        """Mix of successful and failed fetches handled gracefully."""

        async def mock_fetch(url: str, **kwargs) -> dict:
            if "bad" in url:
                return {"url": url, "error": "Connection refused"}
            return {
                "url": url,
                "status_code": 200,
                "text": "<p>Good</p>",
                "headers": {},
            }

        with patch("app.tools.web_tools.fetch_url", side_effect=mock_fetch):
            result = await web_multi_fetch_tool.ainvoke(
                {"urls": ["https://good.com", "https://bad.com"]}
            )
        assert "Good" in result
        assert "Connection refused" in result

    async def test_handles_exception_in_fetch(self):
        """If fetch_url raises, it's caught via gather."""

        async def mock_fetch(url: str, **kwargs) -> dict:
            if "crash" in url:
                raise RuntimeError("crash")
            return {
                "url": url,
                "status_code": 200,
                "text": "<p>OK</p>",
                "headers": {},
            }

        with patch("app.tools.web_tools.fetch_url", side_effect=mock_fetch):
            result = await web_multi_fetch_tool.ainvoke(
                {"urls": ["https://ok.com", "https://crash.com"]}
            )
        assert "OK" in result
        assert "crash" in result.lower()
