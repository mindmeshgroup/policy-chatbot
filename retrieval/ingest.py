import os
import tempfile
import asyncio  
import concurrent.futures
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup

# imports
from retrieval.utils.metadata_factory import extract_metadata_and_chunk
from retrieval.utils.vector_engine import clean_and_upsert
from retrieval.utils.state_manager import get_all_states, save_state

# Modified imports to fetch relocated helpers from crawler.py
from retrieval.utils.crawler import (
    get_all_policy_links, 
    _fetch_html,
    check_if_updated,
    parse_document_title
)

# configuration
COLLECTION_NAME = "university_policies"
WEB_HUB_URL = "https://policies.latrobe.edu.au/browse"
LOCAL_FOLDER = "./policy_pdfs/"

MAX_CPU_WORKERS = 2 
MAX_CONCURRENT_TASKS = 10 

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
        temp_path = None
        if is_web and html_content:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".html", mode="w", encoding="utf-8") as temp_file:
                temp_file.write(html_content)
                temp_path = temp_file.name
            
            # The Temp File Leak (Guarantee Cleanup)
            try:
                result = worker_converter.convert(temp_path)
            finally:
                if temp_path and os.path.exists(temp_path):
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

        # --- THE SECTION 99 FILTER FIX ---
        filtered_payloads = []
        for p in payloads:
            clean_text = re.sub(r'\s+', ' ', p.get('content', '')).strip()
            breadcrumb = p.get('breadcrumb', '')
            
            # If the chunk contains the injected Section 99 table, drop it!
            if "SECTION 99" not in breadcrumb and "SECTION 99" not in clean_text:
                filtered_payloads.append(p)
                
        payloads = filtered_payloads
        
        if not payloads:
            return True, source, "Skipped (Only metadata found)"
        # ---------------------------------

        clean_and_upsert(COLLECTION_NAME, payloads)
        real_title = payloads[0].get('document_title', temp_title) if payloads else temp_title
        
        # Live print immediately after embedding
        print(f"{doc_tracker} Successfully Indexed: {real_title} ({len(payloads)} chunks)")
        return True, source, f"{real_title} ({len(payloads)} chunks)"
        
    except Exception as e:
        print(f"{doc_tracker}  Error: {str(e)}")
        return False, source, f"Error: {str(e)}"

def run_web_ingestion():
    print(f"\n---  WEB CRAWL MODE (STREAMING PARALLEL) ---")
    all_links = get_all_policy_links(WEB_HUB_URL)
    target_urls = [url for url in all_links if "/document/view.php?id=" in url][:10]
    
    if not target_urls:
        return print("No policy links found.")

    test_urls = sorted(list(set(target_urls)))
    ledger = get_all_states()
    
    print(f"   Running Parallel CDC Check for {len(test_urls)} policies...")
    
    # Network/WAF Risk: The CDC "Thread Bomb"
    async def parallel_cdc():
        sem = asyncio.Semaphore(10) # Max 10 concurrent CDC checks
        
        async def bounded_check(url):
            async with sem:
                # Updated to directly await since check_if_updated is now an async function
                return await check_if_updated(url, ledger)
                
        tasks = [asyncio.create_task(bounded_check(url)) for url in test_urls]
        return await asyncio.gather(*tasks)

    cdc_results = asyncio.run(parallel_cdc())
    links_to_process = []
    modified_dates_dict = {}
    for needs_update, url, modified_date in cdc_results:
        if needs_update:
            links_to_process.append(url)
            modified_dates_dict[url] = modified_date
        else:
            doc_title = parse_document_title(url)
            print(f"[SKIPPED] {doc_title} | {url} (No changes detected)")
    
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
                    
                    # 1. FIND THE HIDDEN LINK 
                    metadata_url = next((urljoin(url, a['href']) for a in soup.find_all('a', href=True) 
                                       if "status and details" in a.text.lower() or "status & details" in a.text.lower()), None)
                    
                    if metadata_url:
                        meta_html = await _fetch_html(metadata_url)
                        if meta_html:
                            meta_soup = BeautifulSoup(meta_html, 'html.parser')
                            
                            # 2. AGGRESSIVE EXTRACTION
                            meta_content = (meta_soup.find('table') or 
                                            meta_soup.find('div', class_='document-content') or 
                                            meta_soup.body)
                            
                            if meta_content:
                                # 3. STITCHING & TAGGING
                                wrapper = soup.new_tag("div", id="injected-status-details", style="border-top: 5px solid red;")
                                
                                meta_header = soup.new_tag("h1")
                                meta_header.string = "SECTION 99 - STATUS AND DETAILS (METADATA)"
                                
                                wrapper.append(meta_header)
                                wrapper.append(meta_content)
                                
                                # Inject at the VERY TOP (index 0) so Docling doesn't delete it!
                                if soup.body:
                                    soup.body.insert(0, wrapper)
                    
                    # 4. QUEUE FOR CONVERSION
                    await html_queue.put((idx, url, str(soup)))

            # Run producer tasks concurrently
            tasks = [asyncio.create_task(fetch_task(i, url)) for i, url in enumerate(links_to_process)]
            await asyncio.gather(*tasks)
            # Signal consumers to stop
            for _ in range(MAX_CPU_WORKERS):
                await html_queue.put((None, None, None))

        async def consumer(pool):
            loop = asyncio.get_running_loop()
            while True:
                idx, url, html_content = await html_queue.get()
                if url is None: 
                    html_queue.task_done()
                    break
                
                doc_tracker = f"[{idx+1}/{total_docs}]"
                
                if html_content:
                    try:
                        # OOM Silent Deadlocks (Add timeout)
                        success, source, info = await asyncio.wait_for(
                            loop.run_in_executor(
                                pool, cpu_bound_conversion_and_storage, url, True, html_content, doc_tracker
                            ),
                            timeout=300 
                        )
                        final_results.append((success, source, info))
                        
                        # --- THE INSTANT CHECKPOINT ---
                        if success:
                            state_val = modified_dates_dict.get(source, "web_processed")
                            # Blocking the Async Loop (Offload SQLite write)
                            await asyncio.to_thread(save_state, source, state_val)
                    except asyncio.TimeoutError:
                        final_results.append((False, url, "Process Timeout or Worker Killed"))
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

# --- NEW UNIFIED LOCAL HELPER ---
def _process_local_batch(files, is_parallel=True):
    """DRY Helper to process files concurrently or sequentially."""
    if not files:
        return

    if is_parallel:
        print(f"\n--> Processing {len(files)} files in PARALLEL...")
        with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_CPU_WORKERS, initializer=init_worker) as pool:
            future_to_file = {
                pool.submit(cpu_bound_conversion_and_storage, os.path.join(LOCAL_FOLDER, f), False, None, f"[{'HTML' if f.endswith('.html') else 'FILE'} {i+1}/{len(files)}]"): f 
                for i, f in enumerate(files)
            }
            
            for future in concurrent.futures.as_completed(future_to_file):
                filename = future_to_file[future]
                source_path = os.path.join(LOCAL_FOLDER, filename)
                try:
                    success, source, info = future.result()
                    if success:
                        save_state(source_path, "local_processed")
                except Exception as e:
                    print(f"Error retrieving result for {filename}: {e}")
    else:
        print(f"\n--> Processing {len(files)} files SEQUENTIALLY to save RAM...")
        init_worker() # Initialize the worker in the main thread
        for i, f in enumerate(files):
            filename = f
            source_path = os.path.join(LOCAL_FOLDER, filename)
            try:
                # Call the function directly, bypassing the pool entirely
                success, source, info = cpu_bound_conversion_and_storage(
                    source_path, False, None, f"[PDF {i+1}/{len(files)}]"
                )
                if success:
                    save_state(source_path, "local_processed")
            except Exception as e:
                print(f"Error retrieving result for {filename}: {e}")

def run_local_ingestion():
    print(f"\n---  LOCAL BATCH MODE (MULTIPROCESSING + SAFE PDF) ---")
    if not os.path.exists(LOCAL_FOLDER):
        return print(f"Error: {LOCAL_FOLDER} folder missing.")
    
    files = [f for f in os.listdir(LOCAL_FOLDER) if f.lower().endswith(('.pdf', '.html'))]
    ledger = get_all_states()
    pending_files = []
    for f in files:
        source_path = os.path.join(LOCAL_FOLDER, f)
        if source_path not in ledger:
            pending_files.append(f)
        else:
            doc_title = parse_document_title(source_path)
            print(f"[SKIPPED] {doc_title} (Already in ledger)")
            
    total = len(pending_files)
    
    if total == 0:
        return print("All local files are already fully ingested.")

    print(f"Skipped {len(files) - total} already ingested files. Processing {total} new files...")

    pdf_files = [f for f in pending_files if f.lower().endswith('.pdf')]
    html_files = [f for f in pending_files if f.lower().endswith('.html')]

    # 1. Process HTMLs using the Fast Parallel Pool
    _process_local_batch(html_files, is_parallel=True)

    # 2. Process PDFs SEQUENTIALLY to prevent std::bad_alloc RAM crashes
    _process_local_batch(pdf_files, is_parallel=False)

def run_debug(target):
    """
    Diagnostic tool to inspect how Docling/Crawl4AI sees a document.
    Currently compatible with the standalone _fetch_html (no persistent crawler yet).
    """
    init_worker() 
    
    if target.startswith("http"):
        async def quick_fetch():
            # Using your current crawler.py which only takes the URL
            raw_html = await _fetch_html(target)
            if not raw_html: 
                return None
            
            soup = BeautifulSoup(raw_html, 'html.parser')
            
            # Metadata Injection logic for the debugger
            metadata_url = next((urljoin(target, a['href']) for a in soup.find_all('a', href=True) 
                               if "status and details" in a.text.lower() or "status & details" in a.text.lower()), None)
            
            if metadata_url:
                meta_html = await _fetch_html(metadata_url)
                if meta_html:
                    meta_soup = BeautifulSoup(meta_html, 'html.parser')
                    meta_content = (meta_soup.find('table') or meta_soup.find('div', class_='document-content') or meta_soup.body)
                    
                    if meta_content:
                        wrapper = soup.new_tag("div")
                        meta_header = soup.new_tag("h1")
                        meta_header.string = "SECTION 99 - STATUS AND DETAILS (METADATA)"
                        wrapper.append(meta_header)
                        wrapper.append(meta_content)
                        
                        if soup.body:
                            soup.body.insert(0, wrapper) # Inject at the very top!
                      
            return str(soup)

        print(f"\n[DEBUG] Fetching and injecting metadata for: {target}")
        html = asyncio.run(quick_fetch())
        # Passing HTML to Docling converter
        success, _, info = cpu_bound_conversion_and_storage(target, True, html, "[DEBUG]")
        
    else:
        # --- THE DOCLING PDF/LOCAL DIAGNOSTIC TOOL ---
        print(f"\n[DIAGNOSTIC MODE] Opening local file: {target}...")
        
        # Access the global worker_converter initialized by init_worker()
        global worker_converter
        result = worker_converter.convert(target)
        
        from docling.chunking import HierarchicalChunker
        chunker = HierarchicalChunker()
        chunks = list(chunker.chunk(result.document))
        
        print(f"\n--- DOCLING PARSE TREE ({len(chunks)} Chunks) ---")
        for i, chunk in enumerate(chunks[:20]): # Limits to first 20 chunks for clarity
            # Get the heading path if it exists
            headers = getattr(chunk.meta, 'headings', [])
            header_str = " > ".join(headers) if headers else "TOP LEVEL (NO HEADING)"
            
            # Find out what Docling labeled this specific piece of text
            labels = [str(getattr(item, "label", "Unknown")) for item in getattr(chunk.meta, "doc_items", [])]
            label_str = ", ".join(labels) if labels else "NO LABEL"
            
            print(f"\nCHUNK [{i}]")
            print(f"Detected Hierarchy: {header_str}")
            print(f"Docling Label:      {label_str}")
            print(f"Raw Text Preview:\n{chunk.text.strip()[:300]}...") # Previews first 300 chars
            print("-" * 60)
            
        print("\nDiagnostic complete. Exiting before database insertion.")
        return

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