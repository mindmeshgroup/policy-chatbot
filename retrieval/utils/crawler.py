import asyncio
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

WAIT_JS = "await new Promise(r => setTimeout(r, 2000));"

# SEMAPHORE: Limits concurrent browser tabs to 5 
browser_semaphore = asyncio.Semaphore(5)

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
            
            # skips non-policy administrative pages and pagination links
            blacklist = [
                'login', 'contact', 'search', 'intranet', 'feedback', 
                'help', 'mailto:', 'print', 'summary=', '/browse', 'home.php'
            ]
            
            if not any(junk in clean_href_lower for junk in blacklist):
                policy_urls.add(clean_href)
                    
        return list(policy_urls)

async def _fetch_html(url: str) -> str:
    """Fetching - Uses Crawl4AI to get the raw HTML DOM string. Includes Semaphore & Fault Isolation."""
    config = CrawlerRunConfig(js_code=WAIT_JS)
    
    # 1. SEMAPHORE: Ensures no more than 5 requests hit the server at the exact same time
    async with browser_semaphore:
        try:
            async with AsyncWebCrawler() as crawler:
                result = await crawler.arun(url=url, config=config)
                if result.success:
                    return result.html 
                else:
                    # 2. FAULT ISOLATION: Log error but don't crash, return empty string
                    print(f"    [FAULT ISOLATED] Crawl4AI failed to fetch {url}: {result.error_message}")
                    return ""
        except Exception as e:
            # Catching any other timeout/connection errors
            print(f"    [FAULT ISOLATED] Exception fetching {url}: {e}")
            return ""

def get_all_policy_links(base_url: str) -> list:
    """Synchronous wrapper for _scout_links"""
    return asyncio.run(_scout_links(base_url))

def get_raw_html(url: str) -> str:
    """Synchronous wrapper for _fetch_html"""
    return asyncio.run(_fetch_html(url))