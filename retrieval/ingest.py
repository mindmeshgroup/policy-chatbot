import os
import tempfile
import json
import requests
import hashlib
from urllib.parse import urlparse, parse_qs, urljoin
from bs4 import BeautifulSoup
from docling.document_converter import DocumentConverter
from utils.metadata_factory import extract_metadata_and_chunk
from utils.vector_engine import clean_and_upsert
from utils.crawler import get_all_policy_links, get_raw_html

# CONFIGURATION 
COLLECTION_NAME = "university_policies"
WEB_HUB_URL = "https://policies.latrobe.edu.au/browse"
LOCAL_FOLDER = "./policy_pdfs/"
LEDGER_FILE = "ingestion_ledger.json"

def load_ledger():
    """Loads the history of processed files."""
    if os.path.exists(LEDGER_FILE):
        with open(LEDGER_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_ledger(ledger):
    """Saves the history of processed files."""
    with open(LEDGER_FILE, 'w') as f:
        json.dump(ledger, f, indent=4)

def check_if_updated(url, ledger):
    """Checks if the page has changed using a text-only content hash to bypass dynamic PHP tokens."""
    try:
        # HEAD request
        response = requests.head(url, allow_redirects=True, timeout=5)
        last_modified = response.headers.get('Last-Modified')
        
        if last_modified:
            if ledger.get(url) == last_modified:
                return False, last_modified
            return True, last_modified
            
        # Hash the TEXT, not the HTML code
        get_response = requests.get(url, timeout=5)
        soup = BeautifulSoup(get_response.content, 'html.parser')
        
        # stripping away all hidden PHP session tokens, scripts, and metadata
        clean_text = soup.text.strip() 
        page_hash = hashlib.md5(clean_text.encode('utf-8')).hexdigest()
        
        if ledger.get(url) == page_hash:
            return False, page_hash # Hash matches, skip 
            
        return True, page_hash # Hash is new, process
        
    except Exception:
        return True, "Forced Update (Ping Failed)"

def parse_document_title(source: str) -> str:
    parsed_url = urlparse(source)
    query_params = parse_qs(parsed_url.query)
    if 'id' in query_params:
        return f"Policy ID: {query_params['id'][0]}"
    base = os.path.basename(parsed_url.path.rstrip('/'))
    name = os.path.splitext(base)[0]
    title = name.replace('-', ' ').replace('_', ' ').title()
    return title if title and title.lower() != 'view' else "Unknown Document"

def process_and_store(source: str, is_web: bool, converter: DocumentConverter):
    temp_title = parse_document_title(source)
    try:
        if is_web and not source.lower().endswith('.pdf'):
            print(f"   Fetching Main Policy: {temp_title}...")
            raw_html_string = get_raw_html(source)
            soup = BeautifulSoup(raw_html_string, 'html.parser')
            
            # Dynamic Scouting
            metadata_url = None
            for a_tag in soup.find_all('a', href=True):
                if "status and details" in a_tag.text.lower():
                    metadata_url = urljoin(source, a_tag['href'])
                    break
            
            if metadata_url:
                print(f"    Fetching  Metadata: {metadata_url}...")
                meta_html = get_raw_html(metadata_url)
                meta_soup = BeautifulSoup(meta_html, 'html.parser')
                meta_content = meta_soup.find('div', class_='document-content') or meta_soup.find('table')
                
                if meta_content:
                    header = soup.new_tag("h1")
                    header.string = "Status and Details Table"
                    soup.body.append(header)
                    soup.body.append(meta_content)
            
            combined_html = str(soup)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".html", mode="w", encoding="utf-8") as temp_file:
                temp_file.write(combined_html)
                temp_path = temp_file.name
            
            result = converter.convert(temp_path)
            os.remove(temp_path)
        else:
            print(f"    Processing File: {temp_title}...")
            result = converter.convert(source)

        markdown_text = result.document.export_to_markdown()
        if len(markdown_text) < 200:
            print(f"    SKIPPED: {temp_title} (Insufficient content)")
            return True

        payloads = extract_metadata_and_chunk(result.document, source_path=source)
        if not payloads:
            print(f"    Failed to generate chunks for {temp_title}")
            return False

        # Storage
        clean_and_upsert(COLLECTION_NAME, payloads)
        real_title = payloads[0].get('document_title', temp_title)
        print(f"    Indexed: {real_title} ({len(payloads)} chunks created)")
        return True
        
    except Exception as e:
        print(f"    Error processing {temp_title}: {e}")
        return False

def run_web_ingestion(converter):
    print(f"\n---  WEB CRAWL MODE ---")
    all_links = get_all_policy_links(WEB_HUB_URL)
    
    target_urls = [url for url in all_links if "/document/view.php?id=" in url]
    
    if not target_urls:
        return print("No policy links found.")

    # FULL SCRAPE: Process ALL discovered policies
    test_urls = sorted(list(set(target_urls)))
    print(f"   Scouted {len(target_urls)} policy links. Processing ALL documents...")

    # Load the CDC Ledger
    ledger = load_ledger()
    processed_count = 0

    for i, url in enumerate(test_urls):
        print(f"\n[{i+1}/{len(test_urls)}] ------------------------------")
        
        # Check the Ledger before doing any expensive work
        needs_update, modified_date = check_if_updated(url, ledger)
        
        if not needs_update:
            print(f"    SKIPPING: Already up to date ({url})")
            continue
            
        # If new or updated, run ingestion logic
        success = process_and_store(url, is_web=True, converter=converter)
        
        # If successful, write it to the ledger so we don't process it again tomorrow
        if success:
            ledger[url] = modified_date
            save_ledger(ledger)
            processed_count += 1
            
    print(f"\n Batch Complete. Successfully ingested {processed_count} new/updated policies.")

def run_local_ingestion(converter):
    print(f"\n---  LOCAL BATCH MODE ---")
    if not os.path.exists(LOCAL_FOLDER):
        return print(f"Error: {LOCAL_FOLDER} folder missing.")
    
    files = [f for f in os.listdir(LOCAL_FOLDER) if f.lower().endswith(('.pdf', '.html'))]
    for i, file_name in enumerate(files):
        print(f"\n[{i+1}/{len(files)}] ------------------------------")
        file_path = os.path.join(LOCAL_FOLDER, file_name)
        process_and_store(file_path, is_web=False, converter=converter)

if __name__ == "__main__":
    print("========================================")
    print("La Trobe PolicyDB - Core Ingestion")
    print("========================================")
    print("1. Local Disk Batch")
    print("2. Live Web Crawl (Full Site Scrape)")
    print("3. SINGLE TARGET DEBUG")
    
    choice = input("\nEnter 1, 2, or 3: ").strip()
    conv = DocumentConverter()
    
    if choice == '1': run_local_ingestion(conv)
    elif choice == '2': run_web_ingestion(conv)
    elif choice == '3':
        target = input("\nEnter URL or path: ").strip()
        process_and_store(target, is_web=target.startswith("http"), converter=conv)
    else: print("Invalid choice.")