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
    """Aiohttp asynchronous fetch with exponential backoff."""
    for attempt in range(retries):
        try:
            async with session.get(url, timeout=5) as response:
                response.raise_for_status()
                return await response.text()
        except Exception as e:
            if attempt == retries - 1:
                print(f"    [Network Error] Failed to fetch {url} after {retries} attempts: {e}")
                return ""
            await asyncio.sleep(backoff_factor * (attempt + 1))
    return ""

async def check_if_updated(url: str, ledger: dict) -> tuple:
    """Change Data Capture (CDC) check. Returns (needs_update, url, new_hash)."""
    try:
        async with aiohttp.ClientSession() as session:
            raw_html = await fetch_with_retry(session, url)
            if not raw_html:
                return False, url, None

            soup = BeautifulSoup(raw_html, 'html.parser')
            
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

            for noisy_tag in soup(['nav', 'footer', 'header', 'aside', 'script', 'style', 'meta']):
                noisy_tag.decompose()
                
            main_content = soup.find('div', class_='document-content') or soup.find('main') or soup.body
            
            if main_content:
                for tag in main_content.find_all(True):
                    tag.attrs = {} 
                
            content_to_hash = str(main_content) + meta_html_string
            page_hash = hashlib.md5(content_to_hash.encode('utf-8')).hexdigest()
            soup.decompose() 
            
            if ledger.get(url) == page_hash:
                return False, url, page_hash 
                
            return True, url, page_hash 
            
    except Exception as e:
        print(f"    [CDC Error] {url}: {e}")
        return False, url, None 

# ==========================================
# CORE CRAWLER FUNCTIONS
# ==========================================

async def _scout_links(base_url: str) -> list:
    """Navigation: actual policy links"""
    config = CrawlerRunConfig(js_code=WAIT_JS, exclude_external_links=True)
    
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
                
            clean_href_lower = clean_href.lower()
            
            # [THE FIX] Poisoned Link Trap: Expanded to include non-HTML files
            blacklist = [
                'login', 'contact', 'search', 'intranet', 'feedback', 
                'help', 'mailto:', 'print', 'summary=', '/browse', 'home.php',
                '.jpg', '.png', '.pdf', '.docx', '.xlsx', '.zip'
            ]
            
            if not any(junk in clean_href_lower for junk in blacklist):
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