import asyncio
import hashlib
import random
import logging
import os
import re
from html import escape, unescape
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urljoin

import aiohttp
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

RAW_HTML_DIR = Path(__file__).resolve().parents[2] / "data" / "0_raw_html"
RAW_HTML_DIR.mkdir(parents=True, exist_ok=True)

_browser_semaphore = None
_semaphore_loop = None
ALLOWED_HOST = "policies.latrobe.edu.au"

# These markers indicate that a fetched response is an authentication page
# rather than publicly ingestible policy content.
SSO_RESTRICTED_MARKERS = (
    "microsoft.com/en-gb/servicesagreement",
    "sign in to your account",
    "login.microsoftonline.com",
    "single sign on",
    "single sign-on",
    "authentication required",
    "access denied",
    "shibboleth",
    "saml",
)

# Full-library validation confirmed that Policy 268 requires authenticated
# access. Additional confirmed restricted IDs can be supplied without editing
# the crawler, for example: KNOWN_RESTRICTED_POLICY_IDS="268,999".
KNOWN_RESTRICTED_POLICY_IDS = {
    item.strip()
    for item in os.getenv("KNOWN_RESTRICTED_POLICY_IDS", "268").split(",")
    if item.strip()
}


def get_policy_id(url: str) -> str | None:
    """Extracts the policy identifier from a Policy Library document URL."""
    query_params = parse_qs(urlparse(url).query)
    policy_ids = query_params.get("id", [])
    return policy_ids[0] if policy_ids else None


def is_known_restricted_url(url: str) -> bool:
    """Returns True for source URLs confirmed to require authenticated access."""
    policy_id = get_policy_id(url)
    return policy_id in KNOWN_RESTRICTED_POLICY_IDS if policy_id else False


def is_restricted_page(html_content: str) -> bool:
    """Returns True when fetched HTML appears to be an authentication page."""
    html_lower = html_content.casefold()
    return any(marker in html_lower for marker in SSO_RESTRICTED_MARKERS)


def restricted_page_hash(url: str) -> str:
    """
    Creates a stable CDC value for an intentionally excluded restricted source.
    """
    return hashlib.sha256(
        f"restricted::{url}".encode("utf-8")
    ).hexdigest()

def get_browser_semaphore():
    global _browser_semaphore, _semaphore_loop
    current_loop = asyncio.get_running_loop()
    if _browser_semaphore is None or _semaphore_loop != current_loop:
        _browser_semaphore = asyncio.Semaphore(5)
        _semaphore_loop = current_loop
    return _browser_semaphore

def validate_policy_url(url: str) -> None:
    if urlparse(url).hostname != ALLOWED_HOST:
        raise ValueError(f"Unsupported policy source URL: {url}")

def parse_document_label(source: str) -> str:
    parsed_url = urlparse(source)
    query_params = parse_qs(parsed_url.query)
    if 'id' in query_params:
        return f"Policy ID: {query_params['id'][0]}"
    return Path(parsed_url.path).stem.replace('-', ' ').replace('_', ' ').title()

# ==========================================
# UNIFIED METADATA HELPERS
# ==========================================
def extract_real_html_title(soup: BeautifulSoup) -> str | None:
    """Extracts the  document title from HTML structure."""
    # 1. Try the explicit <meta name="title"> tag (Most Reliable)
    meta_title = soup.find("meta", attrs={"name": "title"})
    if meta_title and meta_title.get("value"):
        return meta_title["value"].strip()

    # 2. Try the main <title> tag and strip the website suffix
    page_title = soup.find("title")
    if page_title:
        # Splits "University Vehicle Fleet Policy / Document / La Trobe..."
        return page_title.text.split(" / ")[0].strip()

    # 3. Try the first <h1> tag that isn't a section header
    for h1_tag in soup.find_all("h1"):
        if "Section" not in h1_tag.text and "Part" not in h1_tag.text:
            return h1_tag.text.strip()

    return None
def find_metadata_url(soup: BeautifulSoup, page_url: str) -> str | None:
    for a_tag in soup.find_all("a", href=True):
        label = a_tag.get_text(" ", strip=True).lower()
        if "status and details" in label or "status & details" in label:
            metadata_url = urljoin(page_url, a_tag["href"])
            validate_policy_url(metadata_url)
            return metadata_url
    return None

def find_metadata_container(soup: BeautifulSoup):
    return soup.find("div", class_="document-content") or soup.find("table")

# ==========================================
# CORE CRAWLER LOGIC
# ==========================================
def save_html_to_disk(url: str, title: str, html_content: str) -> str:
    """Saves downloaded HTML and its source metadata to the staging directory."""
    validate_policy_url(url)
    safe_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    filepath = RAW_HTML_DIR / f"{safe_hash}.html"

    # Split string bypasses markdown parsers to ensure the HTML comment is written to disk
    c_open = "<!" + "--"
    c_close = "--" + ">"

    metadata_header = (
        f"{c_open} source_url: {escape(url)} {c_close}\n"
        f"{c_open} document_title: {escape(title)} {c_close}\n"
    )

    filepath.write_text(metadata_header + html_content, encoding="utf-8")
    return str(filepath)

async def fetch_with_retry(session: aiohttp.ClientSession, url: str, retries: int = 3, backoff_factor: int = 2) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    last_error: Exception | None = None

    for attempt in range(retries):
        try:
            async with session.get(url, headers=headers, timeout=10) as response:
                response.raise_for_status()
                return await response.text()
        except Exception as exc:
            last_error = exc
            if attempt < retries - 1:
                await asyncio.sleep(backoff_factor * (attempt + 1) + random.uniform(0.5, 1.5))

    raise RuntimeError(f"Failed to fetch URL after {retries} attempts: {url}") from last_error

def extract_normalised_text(container) -> str:
    if container is None: return ""
    return "\n".join(container.stripped_strings)

async def check_if_updated(
    session: aiohttp.ClientSession,
    url: str,
    ledger: dict,
) -> tuple[bool, str, str, bool]:
    """
    Checks source changes and identifies pages excluded by authentication.

    The final returned value indicates whether the page is restricted. A
    restricted source receives a stable ledger hash and is excluded from
    public indexing rather than failing the entire publication run.
    """
    validate_policy_url(url)

    try:
        # Policy 268 is a confirmed SSO-restricted policy source. Handle it
        # before attempting to parse it as public HTML content.
        if is_known_restricted_url(url):
            page_hash = restricted_page_hash(url)
            return ledger.get(url) != page_hash, url, page_hash, True

        raw_html = await fetch_with_retry(session, url)

        # Detect other authentication pages from their returned HTML.
        if is_restricted_page(raw_html):
            page_hash = restricted_page_hash(url)
            return ledger.get(url) != page_hash, url, page_hash, True

        soup = BeautifulSoup(raw_html, "html.parser")

        metadata_url = find_metadata_url(soup, url)
        metadata_text = ""

        if metadata_url:
            meta_raw = await fetch_with_retry(session, metadata_url, retries=2)

            # A public policy remains indexable when only its separate
            # status/details page requires authentication.
            if not is_restricted_page(meta_raw):
                meta_soup = BeautifulSoup(meta_raw, "html.parser")
                metadata_container = find_metadata_container(meta_soup)
                metadata_text = extract_normalised_text(metadata_container)

        for noisy_tag in soup(
            ["nav", "footer", "header", "aside", "script", "style", "meta"]
        ):
            noisy_tag.decompose()

        main_content = (
            soup.find("div", class_="document-content")
            or soup.find("main")
            or soup.body
        )

        if main_content is None:
            raise RuntimeError(
                f"Could not find policy content in fetched page: {url}"
            )

        main_text = extract_normalised_text(main_content)

        if not main_text.strip():
            raise RuntimeError(
                f"Policy content was empty after parsing: {url}"
            )

        content_to_hash = main_text + "\n" + metadata_text
        page_hash = hashlib.sha256(
            content_to_hash.encode("utf-8")
        ).hexdigest()

        return ledger.get(url) != page_hash, url, page_hash, False

    except Exception as exc:
        raise RuntimeError(
            f"Failed while checking whether policy page changed: {url}"
        ) from exc

async def _fetch_html(url: str, crawler: AsyncWebCrawler, retries: int = 2) -> str:
    validate_policy_url(url)
    config = CrawlerRunConfig(delay_before_return_html=2.0, page_timeout=60000, exclude_external_links=True)
    
    async with get_browser_semaphore():
        for attempt in range(1, retries + 1):
            try:
                result = await crawler.arun(url=url, config=config)
                if result.success and result.html: return result.html 
                if attempt == retries: raise RuntimeError(f"Crawl4AI did not return HTML for page: {url}")
            except Exception as exc:
                if attempt == retries: raise RuntimeError(f"Failed to crawl policy page after {retries} attempts: {url}") from exc
                await asyncio.sleep(3)
    raise RuntimeError(f"Unexpected crawler failure for page: {url}")

async def harvest_and_mutate_html(
    url: str,
    title_fallback: str,
    crawler: AsyncWebCrawler,
    raw_html: str | None = None,
) -> str:
    """Stages one accessible policy page and injects non-searchable metadata."""
    if raw_html is None:
        raw_html = await _fetch_html(url, crawler)

    if is_restricted_page(raw_html):
        raise RuntimeError(f"Policy page requires authenticated access: {url}")

    soup = BeautifulSoup(raw_html, 'html.parser')

    real_title = extract_real_html_title(soup)
    final_title = real_title if real_title else title_fallback

    # Convert definition-list metadata into table form so Docling preserves
    # key-value structure more reliably during parsing.
    for dl in soup.find_all('dl'):
        new_table = soup.new_tag('table')
        for dt in dl.find_all('dt'):
            dd = dt.find_next_sibling('dd')
            if dd:
                tr = soup.new_tag('tr')
                td_key, td_val = soup.new_tag('td'), soup.new_tag('td')
                td_key.string, td_val.string = dt.get_text(strip=True), dd.get_text(strip=True)
                tr.append(td_key); tr.append(td_val)
                new_table.append(tr)
        dl.replace_with(new_table)

    metadata_url = find_metadata_url(soup, url)
    if metadata_url:
        meta_html = await _fetch_html(metadata_url, crawler)

        # Keep the main public policy available even when a separate details
        # page requires authentication; missing metadata remains null later.
        if not is_restricted_page(meta_html):
            meta_soup = BeautifulSoup(meta_html, 'html.parser')
            meta_content = find_metadata_container(meta_soup)

            if meta_content:
                wrapper = soup.new_tag("div", id="system-injected-metadata")
                wrapper.append(meta_content)
                if soup.body:
                    soup.body.insert(0, wrapper)

    return save_html_to_disk(url, final_title, str(soup))


async def process_single_url(
    url: str,
    crawler: AsyncWebCrawler,
    session: aiohttp.ClientSession,
    ledger: dict,
) -> dict:
    """
    Checks one source state and stages it when it is publicly accessible.

    The change flag is retained for reporting, but accessible unchanged policies
    are still staged during a full candidate build because it starts empty.
    """
    is_updated, source_url, content_hash, is_restricted = await check_if_updated(
        session,
        url,
        ledger,
    )

    fallback_title = parse_document_label(source_url)

    if is_restricted:
        return {
            "status": "restricted",
            "url": source_url,
            "title": fallback_title,
            "content_hash": content_hash,
            "hash": content_hash,
            "is_updated": is_updated,
        }

    raw_html = await _fetch_html(source_url, crawler)

    # Recheck the browser-rendered response because an authentication redirect
    # may only become visible after the page is rendered by Crawl4AI.
    if is_restricted_page(raw_html):
        page_hash = restricted_page_hash(source_url)
        return {
            "status": "restricted",
            "url": source_url,
            "title": fallback_title,
            "content_hash": page_hash,
            "hash": page_hash,
            "is_updated": ledger.get(source_url) != page_hash,
        }

    file_path = await harvest_and_mutate_html(
        source_url,
        fallback_title,
        crawler,
        raw_html=raw_html,
    )

    # Read back the title inserted by the crawler so worker logs use the
    # official policy title rather than the URL-based fallback label.
    staged_header = Path(file_path).read_text(encoding="utf-8")[:2048]
    title_match = re.search(
        r"document_title:\s*(.*?)\s*-->",
        staged_header,
        re.IGNORECASE,
    )
    title = (
        unescape(title_match.group(1).strip())
        if title_match
        else fallback_title
    )

    return {
        "status": "staged",
        "url": source_url,
        "title": title,
        "file_path": file_path,
        "content_hash": content_hash,
        "hash": content_hash,
        "is_updated": is_updated,
    }


async def scout_policy_links(base_url: str) -> list[str]:
    validate_policy_url(base_url)
    config = CrawlerRunConfig(delay_before_return_html=2.0, exclude_external_links=True)
    async with AsyncWebCrawler(verbose=False) as crawler:
        result = await crawler.arun(url=base_url, config=config)
        if not result.success: raise RuntimeError(f"Could not load main hub: {base_url}")
        
        links = [urljoin(base_url, link.get('href')) for link in result.links.get('internal', []) if link.get('href') and 'view.php?id=' in link.get('href')]
        return sorted(set(links))

def get_all_policy_links(base_url: str) -> list[str]:
    return asyncio.run(scout_policy_links(base_url))