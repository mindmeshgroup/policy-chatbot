import os
import aiohttp
import asyncio
import hashlib
import random
from urllib.parse import urlparse, parse_qs, urljoin
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

WAIT_JS = "await new Promise(r => setTimeout(r, 2000));"

# SEMAPHORE: Limits concurrent browser tabs to 5 
_browser_semaphore = None
_semaphore_loop = None

def get_browser_semaphore():
    global _browser_semaphore, _semaphore_loop
    current_loop = asyncio.get_running_loop()
    
    # If the semaphore doesn't exist, OR if it belongs to an old/dead loop, create a new one!
    if _browser_semaphore is None or _semaphore_loop != current_loop:
        _browser_semaphore = asyncio.Semaphore(5)
        _semaphore_loop = current_loop
        
    return _browser_semaphore

# ==========================================
# HELPER FUNCTIONS (Moved from ingest.py)
# ==========================================

def parse_document_title(source: str) -> str:
    """Parses a clean title from a URL or file path."""
    parsed_url = urlparse(source)
    query_params = parse_qs(parsed_url.query)
    if 'id' in query_params:
        return f"Policy ID: {query_params['id'][0]}"
    base = os.path.basename(parsed_url.path.rstrip('/'))
    name = os.path.splitext(base)[0]
    return name.replace('-', ' ').replace('_', ' ').title()

async def fetch_with_retry(session: aiohttp.ClientSession, url: str, retries=3, backoff_factor=2) -> str:
    """Aiohttp asynchronous fetch with headers and exponential backoff jitter."""
    # The Fake Mustache: Pretend to be Google Chrome on Windows
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5"
    }
    
    for attempt in range(retries):
        try:
            # Bumped timeout to 10 seconds to account for university server lag
            async with session.get(url, headers=headers, timeout=10) as response:
                response.raise_for_status()
                return await response.text()
        except Exception as e:
            if attempt == retries - 1:
                print(f"    [Network Error] Failed to fetch {url} after {retries} attempts: {e}")
                return ""
            # Add random jitter so retries don't all hit at the exact same millisecond
            import random
            await asyncio.sleep(backoff_factor * (attempt + 1) + random.uniform(0.5, 1.5))
    return ""

async def check_if_updated(url: str, ledger: dict) -> tuple[bool, str, str]:
    """Change Data Capture (CDC) check. Returns (needs_update, url, new_hash)."""
    try:
        async with aiohttp.ClientSession() as session:
            raw_html = await fetch_with_retry(session, url)
            if not raw_html:
                return False, url, ""

            soup = BeautifulSoup(raw_html, 'html.parser')
            
            # --- 1. THE METADATA FETCH ---
            metadata_url = None
            for a_tag in soup.find_all('a', href=True):
                if "status and details" in a_tag.text.lower():
                    metadata_url = urljoin(url, a_tag['href'])
                    break
                    
            meta_html_string = ""
            if metadata_url:
                try:
                    meta_raw = await fetch_with_retry(session, metadata_url, retries=2)
                    if meta_raw:
                        meta_soup = BeautifulSoup(meta_raw, 'html.parser')
                        m_div = meta_soup.find('div', class_='document-content')
                        m_table = meta_soup.find('table')
                        if m_div: meta_html_string += str(m_div)
                        if m_table: meta_html_string += str(m_table)
                        meta_soup.decompose()
                except Exception:
                    pass 

            # --- 2. NOISE REDUCTION ---
            for noisy_tag in soup(['nav', 'footer', 'header', 'aside', 'script', 'style', 'meta']):
                noisy_tag.decompose()
                
            main_content = soup.find('div', class_='document-content') or soup.find('main') or soup.body
            
            # --- 3. THE ATTRIBUTE STRIPPER ---
            if main_content:
                for tag in main_content.find_all(True):
                    tag.attrs = {} 
            
            # --- 4. THE ULTIMATE HASH ---
            content_to_hash = str(main_content) + meta_html_string
            page_hash = hashlib.md5(content_to_hash.encode('utf-8')).hexdigest()
            soup.decompose() 
            
            # --- 5. THE LEDGER DECISION ---
            if ledger.get(url) == page_hash:
                return False, url, page_hash 
                
            return True, url, page_hash 
            
    except Exception as e:
        print(f"    [CDC Error] {url}: {e}")
        # Default to True so we process the file if the CDC check fails
        return True, url, ""

# ==========================================
# CORE CRAWLER FUNCTIONS
# ==========================================

async def _scout_links(base_url: str) -> list:
    """Navigation: actual policy links with explicit DOM wait and structural filtering"""
    
    # 1. THE HARD WAIT (Version-Proof)
    # We combine the scroll and a forced 5-second pause directly into native JavaScript
    js_wait_and_scroll = """
    window.scrollTo(0, document.body.scrollHeight);
    await new Promise(r => setTimeout(r, 5000));
    """

    config = CrawlerRunConfig(
        wait_for="css:a[href*='view.php?id=']", # Wait for at least one policy link
        js_code=js_wait_and_scroll,             # Execute our custom scroll & sleep JS
        wait_until="networkidle",               # Wait for network to quiet down
        exclude_external_links=True
    )
    
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=base_url, config=config)
    
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=base_url, config=config)
        if not result.success: 
            print(f" Scout failed: {result.error_message}")
            return []
        
        internal_links = result.links.get("internal", [])
        policy_urls = set()
        
        for link in internal_links:
            raw_href = link.get('href', '')
            clean_href = raw_href.split('#')[0] 
            
            if not clean_href:
                continue
                
            # Ensure it is an absolute URL
            if clean_href.startswith('/'):
                clean_href = f"https://policies.latrobe.edu.au{clean_href}"
            
            # THE TRUE ENTERPRISE FIX: 
            # If it's in the /document/ folder AND has an ?id=, it is a policy.
            if "/document/" in clean_href.lower() and "id=" in clean_href.lower():
                policy_urls.add(clean_href)
                    
        return list(policy_urls)
         
# [THE FIX] Browser Thrashing: We now pass the 'crawler' object as a parameter
async def _fetch_html(url: str, crawler: AsyncWebCrawler, retries: int = 2) -> str:
    """Fetching - Uses Crawl4AI to get the raw HTML DOM string."""
    
    config = CrawlerRunConfig(
        js_code=WAIT_JS,
        page_timeout=60000, 
        magic=True  
    )
    
    async with get_browser_semaphore():
        # [THE FIX] WAF Politeness Jitter: Wait 0.5 to 1.5 seconds to look human
        await asyncio.sleep(random.uniform(0.5, 1.5))
        
        for attempt in range(retries):
            try:
                # We no longer instantiate AsyncWebCrawler here. We use the one passed in!
                result = await crawler.arun(url=url, config=config)
                
                if result.success:
                    return result.html 
                else:
                    if attempt == retries - 1:
                        print(f"    [FAULT ISOLATED] Crawl4AI failed on {url}")
                    else:
                        await asyncio.sleep(3) 
            except Exception as e:
                if attempt == retries - 1:
                    print(f"    [FAULT ISOLATED] Timeout or Exception on {url}: {e}")
                else:
                    await asyncio.sleep(3)
        
        return ""

def get_all_policy_links(base_url: str) -> list:
    """Synchronous wrapper for _scout_links"""
    return asyncio.run(_scout_links(base_url))

# Updated wrapper to handle the crawler instantiation for standalone calls
def get_raw_html(url: str) -> str:
    """Synchronous wrapper for _fetch_html (creates temporary crawler)"""
    async def run_standalone():
        async with AsyncWebCrawler(verbose=False) as temp_crawler:
            return await _fetch_html(url, temp_crawler)
    return asyncio.run(run_standalone())