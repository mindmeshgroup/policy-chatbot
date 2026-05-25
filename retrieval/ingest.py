import os
import tempfile
import asyncio  
import concurrent.futures
import re
import multiprocessing
import psutil
import hashlib
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler
# imports
from retrieval.utils.metadata_factory import extract_metadata_and_chunk, _consolidate_semantic_chunks
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

 # Dynamically calculate the most efficient worker limit based on your hardware
try:
    total_cores = multiprocessing.cpu_count()
    total_ram_gb = psutil.virtual_memory().total / (1024 ** 3)
    
    # NEW MATH: ~4GB RAM per Docling worker, leaving 6GB for OS + Ollama
    safe_ram_workers = int((total_ram_gb - 6) / 4)
    
    MAX_CPU_WORKERS = max(1, min(total_cores - 1, safe_ram_workers))
    # Optional: Hard cap it at 3 for local laptop execution
    MAX_CPU_WORKERS = min(MAX_CPU_WORKERS, 3) 
except:
    MAX_CPU_WORKERS = 2 # Safer fallback

MAX_CONCURRENT_TASKS = 10 
print(f"[*] Hardware optimally scaled: Running {MAX_CPU_WORKERS} parallel CPU workers.")
def get_file_hash(filepath: str) -> str:
    """Generates an MD5 check-digit hash of a physical file's true content."""
    hasher = hashlib.md5()
    with open(filepath, 'rb') as f:
        buf = f.read(65536) 
        while len(buf) > 0:
            hasher.update(buf)
            buf = f.read(65536)
    return hasher.hexdigest()

def init_worker():
    global worker_converter
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode

    # 1. Enable Advanced Table Extraction for PDFs
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_table_structure = True
    pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE

    # 2. Bind the options to the worker's converter
    worker_converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )
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
        
        # 1. Database execution occurs exactly ONCE
        clean_and_upsert(COLLECTION_NAME, payloads, source)
        real_title = payloads[0].get('document_title', temp_title) if payloads else temp_title
        
        # 2. Terminal log status outputs exactly ONCE
        print(f"{doc_tracker} Successfully Indexed: {real_title} ({len(payloads)} chunks)")
        
        # 3. Safely returns the packaged payload dictionary back to the parent consumer loop
        return True, source, {
            "status": "success",
            "document_title": real_title,
            "payloads": payloads
        }
        
    except Exception as e:
        print(f"{doc_tracker}  Error: {str(e)}")
        return False, source, {
            "status": "failed",
            "error_msg": str(e)
        }
       
ingestion_summary = {
    "successful_titles": [],
    "warnings": {
        "semantic_variance_bypasses": 0,
        "pydantic_validation_failures": 0,
        "worker_timeout_exceptions": 0,
        "atomic_pass_chunks": 0
    }
}

def print_ingestion_dashboard(summary, failed, restricted):
    print("\n" + "="*60)
    print("LA TROBE UNIVERSITY POLICY INGESTION REPORT")
    print("="*60)
    
    print(f"\nSUCCESSFULLY PROCESSED POLICY DOCUMENTS ({len(summary['successful_titles'])} total):")
    if summary['successful_titles']:
        for idx, title in enumerate(sorted(list(set(summary["successful_titles"]))), 1):
            print(f"  {idx}. {title}")
    else:
        print("  None")
        
    print(f"\nRESTRICTED BYPASSES / SSO LOGIN REQUIRED ({len(restricted)} total):")
    if restricted:
        for idx, url in enumerate(sorted(list(set(restricted))), 1):
            print(f"  {idx}. {url}")
    else:
        print("  None")
        
    print(f"\nFAILED / TIMED OUT DOCUMENTS ({len(failed)} total):")
    if failed:
        for idx, url in enumerate(sorted(list(set(failed))), 1):
            print(f"  {idx}. {url}")
    else:
        print("  None")
        
    print("\nPIPELINE ENGINE EXTRACTION & TELEMETRY METRICS:")
    print(f"  - Hierarchical Atomic Chunks:       {summary['warnings']['atomic_pass_chunks']}")
    print(f"  - Cosine Variance Floor Bypasses:   {summary['warnings']['semantic_variance_bypasses']}")
    print(f"  - Pydantic Validation Violations:   {summary['warnings']['pydantic_validation_failures']}")
    print(f"  - Async Worker Processing Timeouts: {summary['warnings']['worker_timeout_exceptions']}")
    print("="*60)
    print("STATUS: Policy Ingestion Completed. Metrics Logged.")
    print("="*60 + "\n")
def run_web_ingestion():
    print(f"\n---  WEB CRAWL MODE (STREAMING PARALLEL) ---")
    all_links = get_all_policy_links(WEB_HUB_URL)
    target_urls = all_links

    if not target_urls:
        return print("No policy links found.")

    test_urls = sorted(list(set(target_urls)))[:175]
    # test_urls = ["https://policies.latrobe.edu.au/document/view.php?id=257"]
    
    ledger = get_all_states()
    
    print(f"   Running Parallel CDC Check for {len(test_urls)} policies...")
    
    # Network/WAF Risk: The CDC "Thread Bomb"
    async def parallel_cdc():
        sem = asyncio.Semaphore(7) # Max 10 concurrent CDC checks
        
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
        
        # 1. Local metrics object initialized for this batch
        batch_metrics = {
            "successful_titles": [],
            "warnings": {
                "semantic_variance_bypasses": 0,
                "pydantic_validation_failures": 0,
                "worker_timeout_exceptions": 0,
                "atomic_pass_chunks": 0
            }
        }
        
        successful_links = []
        failed_links = []
        restricted_links = []
        
        async def producer():
            sem = asyncio.Semaphore(MAX_CONCURRENT_TASKS)
            async with AsyncWebCrawler(verbose=False) as master_crawler:
                async def fetch_task(idx, url):
                    async with sem:
                        raw_html = await _fetch_html(url, master_crawler)
                        if not raw_html:
                            await html_queue.put((idx, url, None))
                            return
                            
                        # SSO Filter
                        login_keywords = ["microsoft.com/en-GB/servicesagreement", "Sign in to your account", "login.microsoftonline.com"]
                        if any(keyword in raw_html for keyword in login_keywords):
                            await html_queue.put((idx, url, "SSO_RESTRICTED")) 
                            return
                        
                        soup = BeautifulSoup(raw_html, 'html.parser')

                        # Table Rewrite Logic
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

                        # Metadata Status Injector
                        metadata_url = next((urljoin(url, a['href']) for a in soup.find_all('a', href=True) 
                                           if "status and details" in a.text.lower() or "status & details" in a.text.lower()), None)
                        if metadata_url:
                            meta_html = await _fetch_html(metadata_url, master_crawler)
                            if meta_html:
                                meta_soup = BeautifulSoup(meta_html, 'html.parser')
                                meta_content = (meta_soup.find('table') or meta_soup.find('div', class_='document-content') or meta_soup.body)
                                if meta_content:
                                    wrapper = soup.new_tag("div", id="injected-status-details", style="border-top: 5px solid red;")
                                    meta_header = soup.new_tag("h1")
                                    meta_header.string = "SECTION 99 - STATUS AND DETAILS (METADATA)"
                                    wrapper.append(meta_header); wrapper.append(meta_content)
                                    if soup.body: soup.body.insert(0, wrapper)
                        
                        await html_queue.put((idx, url, str(soup)))

                tasks = [asyncio.create_task(fetch_task(i, url)) for i, url in enumerate(links_to_process)]
                await asyncio.gather(*tasks)
                
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
                
                if html_content == "SSO_RESTRICTED":
                    await loop.run_in_executor(None, save_state, url, "RESTRICTED_SSO")
                    restricted_links.append(url)    
                elif html_content:
                    try:
                        # Fetch the returned future payload safely
                        success, source, worker_response = await asyncio.wait_for(
                            loop.run_in_executor(
                                pool, cpu_bound_conversion_and_storage, url, True, html_content, doc_tracker
                            ),
                            timeout=900
                        )
                        
                        # FIX: Update batch_metrics targets instead of the dead global reference
                        if success and worker_response.get("status") == "success":
                            successful_links.append(source)
                            state_val = modified_dates_dict.get(source, "web_processed")
                            await loop.run_in_executor(None, save_state, source, state_val)

                            doc_title = worker_response["document_title"]
                            if doc_title not in batch_metrics["successful_titles"]:
                                batch_metrics["successful_titles"].append(doc_title)
                            
                            for chunk in worker_response["payloads"]:
                                method = chunk.get("chunking_method", "")
                                if method == "Semantic-Variance-Bypass":
                                    batch_metrics["warnings"]["semantic_variance_bypasses"] += 1
                                elif method == "Atomic-Pass":
                                    batch_metrics["warnings"]["atomic_pass_chunks"] += 1
                        else:
                            failed_links.append(source)
                            batch_metrics["warnings"]["pydantic_validation_failures"] += 1
                            
                    except asyncio.TimeoutError:
                        print(f"{doc_tracker} Error: Process Timeout on {url}")
                        failed_links.append(url)
                        batch_metrics["warnings"]["worker_timeout_exceptions"] += 1
                else:
                    failed_links.append(url)
                
                html_queue.task_done()

        # Executor Pool Execution
        with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_CPU_WORKERS, initializer=init_worker) as pool:
            prod_task = asyncio.create_task(producer())
            cons_tasks = [asyncio.create_task(consumer(pool)) for _ in range(MAX_CPU_WORKERS)]
            await asyncio.gather(prod_task, *cons_tasks)
            
        return successful_links, failed_links, restricted_links, batch_metrics

        
    # Ensure all four unpacking targets capture the process batch outputs
    successful_links, failed_links, restricted_links, batch_metrics = asyncio.run(process_batch())
    
    # Hand off parameters to the updated clean printer function
    print_ingestion_dashboard(batch_metrics, failed_links, restricted_links)
# --- NEW UNIFIED LOCAL HELPER ---
def _process_local_batch(files, is_parallel=True):
    """DRY Helper to process files concurrently or sequentially."""
    if not files:
        return

    if is_parallel:
        print(f"\n--> Processing {len(files)} files in PARALLEL...")
        with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_CPU_WORKERS, initializer=init_worker) as pool:
            
            # Note: `files` is now a list of tuples: (filename, current_hash)
            # We map the Future object to the entire tuple so we can access the hash later
            future_to_file = {
                pool.submit(
                    cpu_bound_conversion_and_storage, 
                    os.path.join(LOCAL_FOLDER, f[0]), # f[0] is the filename
                    False, 
                    None, 
                    f"[{'HTML' if f[0].endswith('.html') else 'FILE'} {i+1}/{len(files)}]"
                ): f 
                for i, f in enumerate(files)
            }
            
            for future in concurrent.futures.as_completed(future_to_file):
                # Retrieve the tuple (filename, current_hash) from the dictionary
                file_tuple = future_to_file[future]
                filename = file_tuple[0]
                current_hash = file_tuple[1]
                
                source_path = os.path.join(LOCAL_FOLDER, filename)
                abs_path = os.path.abspath(source_path)
                
                try:
                    success, source, info = future.result()
                    if success:
                        # Ensure we save using the absolute path and the dynamic content hash
                        save_state(abs_path, current_hash)
                except Exception as e:
                    print(f"Error retrieving result for {filename}: {e}")
                    
    else:
        print(f"\n--> Processing {len(files)} files SEQUENTIALLY to save RAM...")
        init_worker() # Initialize the worker in the main thread
        
        # `files` is a list of tuples: (filename, current_hash)
        for i, item in enumerate(files):
            filename = item[0]
            current_hash = item[1]
            
            source_path = os.path.join(LOCAL_FOLDER, filename)
            abs_path = os.path.abspath(source_path)
            
            try:
                # Call the function directly, bypassing the pool entirely
                success, source, info = cpu_bound_conversion_and_storage(
                    source_path, False, None, f"[PDF {i+1}/{len(files)}]"
                )
                if success:
                    # Ensure we save using the absolute path and the dynamic content hash
                    save_state(abs_path, current_hash)
            except Exception as e:
                print(f"Error retrieving result for {filename}: {e}")

def run_local_ingestion():
    print(f"\n---  LOCAL BATCH MODE (MULTIPROCESSING + SAFE PDF) ---")
    if not os.path.exists(LOCAL_FOLDER):
        return print(f"Error: {LOCAL_FOLDER} folder missing.")
    
    files = [f for f in os.listdir(LOCAL_FOLDER) if f.lower().endswith(('.pdf', '.html'))]
    ledger = get_all_states()
    pending_files = [] # Will hold tuples of (filename, current_hash)
    
    for f in files:
        source_path = os.path.join(LOCAL_FOLDER, f)
        abs_path = os.path.abspath(source_path)
        
        current_hash = get_file_hash(abs_path)
        
        if abs_path in ledger and ledger[abs_path] == current_hash:
            doc_title = parse_document_title(source_path)
            print(f"[SKIPPED] {doc_title} (Content unmodified)")
        else:
            pending_files.append((f, current_hash))
            
    total = len(pending_files)
    
    if total == 0:
        return print("All local files are already fully ingested.")

    print(f"Skipped {len(files) - total} already ingested files. Processing {total} new files...")

    pdf_files = [f for f in pending_files if f[0].lower().endswith('.pdf')]
    html_files = [f for f in pending_files if f[0].lower().endswith('.html')]

    _process_local_batch(html_files, is_parallel=True)
    _process_local_batch(pdf_files, is_parallel=False)

def run_debug(target):
    from docling_core.transforms.chunker import HierarchicalChunker
    init_worker() 
    process_target = target
    temp_html_path = None
    original_url = target # Define this here so it always exists
    
    if target.startswith("http"):
        async def quick_fetch():
            async with AsyncWebCrawler(verbose=False) as debug_crawler:
                raw_html = await _fetch_html(target, debug_crawler)
                if not raw_html: return None
                soup = BeautifulSoup(raw_html, 'html.parser')
                
                # --- TABLE MUTATION LOGIC ---
                for dl in soup.find_all('dl'):
                    new_table = soup.new_tag('table')
                    for dt in dl.find_all('dt'):
                        dd = dt.find_next_sibling('dd')
                        if dd:
                            tr = soup.new_tag('tr')
                            td_key = soup.new_tag('td')
                            td_key.string = dt.get_text(strip=True)
                            td_val = soup.new_tag('td')
                            td_val.string = dd.get_text(strip=True)
                            tr.append(td_key)
                            tr.append(td_val)
                            new_table.append(tr)
                    dl.replace_with(new_table)
                
                # --- METADATA INJECTION LOGIC ---
                metadata_url = next((urljoin(target, a['href']) for a in soup.find_all('a', href=True) 
                                    if "status and details" in a.text.lower() or "status & details" in a.text.lower()), None)
                if metadata_url:
                    meta_html = await _fetch_html(metadata_url, debug_crawler)
                    if meta_html:
                        meta_soup = BeautifulSoup(meta_html, 'html.parser')
                        meta_content = (meta_soup.find('table') or meta_soup.find('div', class_='document-content') or meta_soup.body)
                        if meta_content:
                            wrapper = soup.new_tag("div", id="injected-status-details", style="border-top: 5px solid red;")
                            meta_header = soup.new_tag("h1")
                            meta_header.string = "SECTION 99 - STATUS AND DETAILS (METADATA)"
                            wrapper.append(meta_header)
                            wrapper.append(meta_content)
                            if soup.body:
                                soup.body.insert(0, wrapper) 
                return str(soup)

        print(f"\n[DEBUG] Fetching raw HTML for: {target}")
        html_content = asyncio.run(quick_fetch())
        
        if html_content:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".html", mode="w", encoding="utf-8") as temp_file:
                temp_file.write(html_content)
                process_target = temp_file.name
                temp_html_path = temp_file.name
    
    print(f"\n[DIAGNOSTIC MODE] Printing Docling chunk structure...")
    global worker_converter
    
    try:
        # 1. Conversion
        result = worker_converter.convert(process_target)
        
        # 2. Chunking (Use production logic)
        chunker = HierarchicalChunker(
    chunker_config={
        "max_tokens": 1500  # Enforce a strict split for chunks that get too big
    }
)
        raw_chunks = list(chunker.chunk(result.document))
        chunks = _consolidate_semantic_chunks(raw_chunks)
        
        # 3. Metadata Factory Logic (Run ONCE outside the loop)
        payloads = extract_metadata_and_chunk(result.document, original_url)
        
        if payloads:
            print(f"\n[DIAGNOSTIC] METADATA FACTORY DECISION:")
            print(f"Final Document Title: '{payloads[0].get('document_title')}'")
            print(f"Source URL:           '{payloads[0].get('source_url')}'")
            print(f"Total Chunks Created: {len(payloads)}")
        
        # 4. Print Tree
        print(f"\n--- DOCLING CONSOLIDATED PARSE TREE ({len(chunks)} Chunks) ---")
        for i, chunk in enumerate(chunks): 
            headers = getattr(chunk.meta, 'headings', [])
            header_str = " > ".join(headers) if headers else "TOP LEVEL"
            print(f"\nCHUNK [{i}]")
            print(f"Hierarchy:  {header_str}")
            print(f"Full Content:\n{chunk.text.strip()}")
            print("-" * 60)
            
    finally:
        if temp_html_path and os.path.exists(temp_html_path):
            os.remove(temp_html_path)
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