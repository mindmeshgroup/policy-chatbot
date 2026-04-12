import asyncio
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

WAIT_JS = "await new Promise(r => setTimeout(r, 2000));"

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
            
            # Skips non-policy administrative pages and pagination links
            blacklist = [
                'login', 'contact', 'search', 'intranet', 'feedback', 
                'help', 'mailto:', 'print', 'summary=', '/browse', 'home.php'
            ]
            
            if not any(junk in clean_href_lower for junk in blacklist):
                policy_urls.add(clean_href)
                    
        return list(policy_urls)

async def _fetch_html(url: str) -> str:
    """Fetching - Uses Crawl4AI to get the raw HTML DOM string."""
    config = CrawlerRunConfig(js_code=WAIT_JS)
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=url, config=config)
        if result.success:
            return result.html 
        else:
            raise Exception(f"Crawl4AI failed to fetch {url}: {result.error_message}")

def get_all_policy_links(base_url: str) -> list:
    return asyncio.run(_scout_links(base_url))

def get_raw_html(url: str) -> str:
    return asyncio.run(_fetch_html(url))