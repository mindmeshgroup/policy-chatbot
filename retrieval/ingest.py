import os
import tempfile
import time
import requests
import hashlib
import asyncio  
import concurrent.futures
from urllib.parse import urlparse, parse_qs, urljoin
from bs4 import BeautifulSoup

# --- IMPORTS ---
from retrieval.utils.metadata_factory import extract_metadata_and_chunk
from retrieval.utils.vector_engine import clean_and_upsert
from retrieval.utils.crawler import get_all_policy_links, _fetch_html
from retrieval.utils.state_manager import get_all_states, save_state

# --- CONFIGURATION ---
COLLECTION_NAME = "university_policies"
WEB_HUB_URL = "https://policies.latrobe.edu.au/browse"
LOCAL_FOLDER = "./policy_pdfs/"

MAX_CPU_WORKERS = 2 
MAX_CONCURRENT_TASKS = 10 

def fetch_with_retry(url, retries=3, backoff_factor=2):
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise e
            time.sleep(backoff_factor * (attempt + 1))

def check_if_updated(url, ledger):
    try:
        get_response = fetch_with_retry(url)
        soup = BeautifulSoup(get_response.content, 'html.parser')
        
        metadata_url = None
        for a_tag in soup.find_all('a', href=True):
            if "status and details" in a_tag.text.lower():
                metadata_url = urljoin(url, a_tag['href'])
                break
                
        meta_html_string = ""
        if metadata_url:
            try:
                meta_response = fetch_with_retry(metadata_url, retries=2)
                meta_soup = BeautifulSoup(meta_response.content, 'html.parser')
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

def parse_document_title(source: str) -> str:
    parsed_url = urlparse(source)
    query_params = parse_qs(parsed_url.query)
    if 'id' in query_params:
        return f"Policy ID: {query_params['id'][0]}"
    base = os.path.basename(parsed_url.path.rstrip('/'))
    name = os.path.splitext(base)[0]
    return name.replace('-', ' ').replace('_', ' ').title()

worker_converter = None

def init_worker():
    global worker_converter
    from docling.document_converter import DocumentConverter
    worker_converter = DocumentConverter()

def cpu_bound_conversion_and_storage(source: str, is_web: bool, html_content: str = None, doc_tracker: str = ""):
    global worker_converter
    temp_title = parse_document_title(source)
    
    print(f"\n{doc_tracker} Parsing and Chunking: {temp_title}...")
    
    try:
        if is_web and html_content:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".html", mode="w", encoding="utf-8") as temp_file:
                temp_file.write(html_content)
                temp_path = temp_file.name
            
            result = worker_converter.convert(temp_path)
            os.remove(temp_path)
        else:
            result = worker_converter.convert(source)

        markdown_text = result.document.export_to_markdown()
        
        if len(markdown_text) < 200:
            msg = f"[UNPROCESSABLE]: Skipped {temp_title} (Insufficient content)"
            print(f"{doc_tracker} Error:  {msg}")
            return True, source, msg

        payloads = extract_metadata_and_chunk(result.document, source_path=source)
        if not payloads:
            msg = f"[UNPROCESSABLE]: Skipped {temp_title} (Failed to chunk)"
            print(f"{doc_tracker} Error:  {msg}")
            return True, source, msg

        clean_and_upsert(COLLECTION_NAME, payloads)
        real_title = payloads[0].get('document_title', temp_title)
        
        # Live print immediately after embedding
        print(f"{doc_tracker} Successfully Indexed: {real_title} ({len(payloads)} chunks)")
        return True, source, f"{real_title} ({len(payloads)} chunks)"
        
    except Exception as e:
        print(f"{doc_tracker}  Error: {str(e)}")
        return False, source, f"Error: {str(e)}"

def run_web_ingestion():
    print(f"\n---  WEB CRAWL MODE (STREAMING PARALLEL) ---")
    all_links = get_all_policy_links(WEB_HUB_URL)
    target_urls = [url for url in all_links if "/document/view.php?id=" in url]
    
    if not target_urls:
        return print("No policy links found.")

    test_urls = sorted(list(set(target_urls)))[:10]
    ledger = get_all_states()
    
    print(f"   Running Parallel CDC Check for {len(test_urls)} policies...")
    async def parallel_cdc():
        tasks = [asyncio.to_thread(check_if_updated, url, ledger) for url in test_urls]
        return await asyncio.gather(*tasks)

    cdc_results = asyncio.run(parallel_cdc())
    
    links_to_process = []
    modified_dates_dict = {}
    for needs_update, url, modified_date in cdc_results:
        if needs_update:
            links_to_process.append(url)
            modified_dates_dict[url] = modified_date
            
    if not links_to_process:
        return print("\n  All policies up to date.")

    total_docs = len(links_to_process)
    print(f"\n Launching Streaming I/O Architecture for {total_docs} documents...")

    async def process_batch():
        html_queue = asyncio.Queue(maxsize=MAX_CONCURRENT_TASKS)
        final_results = []
        
        async def producer():
            sem = asyncio.Semaphore(MAX_CONCURRENT_TASKS)
            async def fetch_task(idx, url):
                async with sem:
                    raw_html = await _fetch_html(url)
                    if not raw_html:
                        await html_queue.put((idx, url, None))
                        return
                    
                    soup = BeautifulSoup(raw_html, 'html.parser')
                    metadata_url = next((urljoin(url, a['href']) for a in soup.find_all('a', href=True) if "status and details" in a.text.lower()), None)
                    
                    if metadata_url:
                        meta_html = await _fetch_html(metadata_url)
                        if meta_html:
                            meta_soup = BeautifulSoup(meta_html, 'html.parser')
                            meta_div = meta_soup.find('div', class_='document-content')
                            meta_table = meta_soup.find('table')
                            if meta_div or meta_table:
                                header = soup.new_tag("h1")
                                header.string = "Status and Details Table"
                                soup.body.append(header)
                                if meta_div: soup.body.append(meta_div)
                                if meta_table: soup.body.append(meta_table)
                    
                    await html_queue.put((idx, url, str(soup)))
            
            await asyncio.gather(*(fetch_task(i+1, url) for i, url in enumerate(links_to_process)))
            
            for _ in range(MAX_CPU_WORKERS):
                await html_queue.put((None, None, None))

        async def consumer(pool):
            loop = asyncio.get_running_loop()
            while True:
                idx, url, html_content = await html_queue.get()
                if url is None: 
                    html_queue.task_done()
                    break
                
                doc_tracker = f"[{idx}/{total_docs}]"
                
                if html_content:
                    success, source, info = await loop.run_in_executor(
                        pool, cpu_bound_conversion_and_storage, url, True, html_content, doc_tracker
                    )
                    final_results.append((success, source, info))
                    
                    # --- THE INSTANT CHECKPOINT ---
                    # Instantly pushes the state to SQLite as soon as Qdrant finishes
                    if success:
                        save_state(source, modified_dates_dict.get(source, "web_processed"))
                else:
                    final_results.append((False, url, "Network Fetch Failed"))
                
                html_queue.task_done()

        with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_CPU_WORKERS, initializer=init_worker) as pool:
            prod_task = asyncio.create_task(producer())
            cons_tasks = [asyncio.create_task(consumer(pool)) for _ in range(MAX_CPU_WORKERS)]
            await asyncio.gather(prod_task, *cons_tasks)
            
        return final_results

    final_results = asyncio.run(process_batch())

    processed_count = sum(1 for s, _, _ in final_results if s)
    print(f"\n Batch Complete. Processed {processed_count} links.")


def run_local_ingestion():
    print(f"\n---  LOCAL BATCH MODE (MULTIPROCESSING) ---")
    if not os.path.exists(LOCAL_FOLDER):
        return print(f"Error: {LOCAL_FOLDER} folder missing.")
    
    files = [f for f in os.listdir(LOCAL_FOLDER) if f.lower().endswith(('.pdf', '.html'))]
    ledger = get_all_states()
    
    pending_files = [f for f in files if os.path.join(LOCAL_FOLDER, f) not in ledger]
    total = len(pending_files)
    
    if total == 0:
        return print("All local files are already fully ingested.")

    print(f"Skipped {len(files) - total} already ingested files. Processing {total} new files...")

    with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_CPU_WORKERS, initializer=init_worker) as pool:
        future_to_file = {
            pool.submit(cpu_bound_conversion_and_storage, os.path.join(LOCAL_FOLDER, f), False, None, f"[{i+1}/{total}]"): f 
            for i, f in enumerate(pending_files)
        }
        
        # --- INSTANT CHECKPOINT FOR LOCAL FILES ---
        for future in concurrent.futures.as_completed(future_to_file):
            filename = future_to_file[future]
            source_path = os.path.join(LOCAL_FOLDER, filename)
            try:
                success, source, info = future.result()
                if success:
                    save_state(source_path, "local_processed")
            except Exception as e:
                print(f"Error retrieving result for {filename}: {e}")

def run_debug(target):
    init_worker() 
    if target.startswith("http"):
        async def quick_fetch():
            return await _fetch_html(target)
        html = asyncio.run(quick_fetch())
        success, _, info = cpu_bound_conversion_and_storage(target, True, html, "[DEBUG]")
    else:
        success, _, info = cpu_bound_conversion_and_storage(target, False, None, "[DEBUG]")

if __name__ == "__main__":
    print("========================================")
    print("La Trobe PolicyDB - Core Ingestion")
    print("========================================")
    print("1. Local Disk Batch")
    print("2. Live Web Crawl (Full Site Scrape)")
    print("3. SINGLE TARGET DEBUG")
    
    choice = input("\nEnter 1, 2, or 3: ").strip()
    
    if choice == '1': run_local_ingestion()
    elif choice == '2': run_web_ingestion()
    elif choice == '3':
        target = input("\nEnter URL or path: ").strip()
        run_debug(target)
    else: print("Invalid choice.")