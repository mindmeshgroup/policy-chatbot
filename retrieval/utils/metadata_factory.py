import hashlib
import re
import uuid
import json
import ollama
from datetime import datetime
from docling.chunking import HierarchicalChunker

# --- CONFIGURATION ---
EXTRACTOR_MODEL = "llama3" 

def standardize_date(date_str):
    """Converts various date formats to ISO 8601 (YYYY-MM-DD)."""
    if not date_str or str(date_str).lower() in ["none", "null", "unknown", "not specified"]:
        return None
    try:
        clean_date = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', str(date_str))
        dt = datetime.strptime(clean_date.strip(), "%d %B %Y")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None

def extract_llm_metadata(markdown_text: str) -> dict:
    """Uses LLM to extract metadata from the Scope and Status Table."""
    
    # 1. INTELLIGENT SCOPE SCOUTING (Research Step 2)
    # Looks for Section 1/2 or the word 'Scope' to identify target audience
    scope_block = ""
    scope_match = re.search(r"(?:Section \d+ - Scope|# Scope).*?(?=# Section|$)", markdown_text, re.IGNORECASE | re.DOTALL)
    if scope_match:
        scope_block = scope_match.group(0)[:1500]

    # 2. STATUS TABLE SCOUTING
    marker = "Status and Details Table"
    match = re.search(re.escape(marker), markdown_text, re.IGNORECASE)
    
    if match:
        table_block = markdown_text[match.start():match.start()+3000]
        analysis_text = f"--- SCOPE SECTION ---\n{scope_block}\n\n--- METADATA TABLE ---\n{table_block}"
    else:
        # Fallback to Top and Tail if no table found
        analysis_text = markdown_text[:4000]

    # 3. UPDATED PROMPT (Research Step 1)
    prompt = f"""
    Strictly extract policy metadata into JSON:
    - "effective_date": Date policy commenced (labeled 'Effective' or 'Commencement').
    - "review_date": Labeled 'Review Date'.
    - "status": e.g. 'Current'.
    - "enquiries_contact": The responsible person or department listed for enquiries.
    - "approval_authority": The body that approved this.
    - "target_cohort": Read the 'SCOPE SECTION'. Return an array containing only these tags: 
       "Student", "Staff", "Researcher", "Public".
       - If it applies to 'all members of the University community', include "Student" and "Staff".
       - If it mentions 'Academic Staff' or 'Professional Staff' only, return ["Staff"].
       - If it mentions 'undergraduate' or 'postgraduate', include "Student".

    RULES:
    1. Only return JSON.
    2. If a field is missing, return null. 
    
    Text:
    {analysis_text}
    """
    
    try:
        response = ollama.chat(
            model=EXTRACTOR_MODEL,
            messages=[{'role': 'user', 'content': prompt}],
            format='json',
            options={'temperature': 0.0}
        )
        return json.loads(response['message']['content'])
    except Exception as e:
        print(f"   LLM Extraction failed: {e}")
        return {} 

def extract_metadata_and_chunk(docling_document, source_path: str):
    markdown_text = docling_document.export_to_markdown()
    
    # Title and ID generation
    title_match = re.search(r'#+\s+(.*)', markdown_text)
    document_title = title_match.group(1).strip() if title_match else "Unknown Policy"
    document_id = hashlib.sha256(document_title.encode('utf-8')).hexdigest()[:12]
    doc_type = "Procedure" if "Procedure" in document_title else "Policy"

    # LLM Extraction Pass
    llm_data = extract_llm_metadata(markdown_text)
    
    # 4. NORMALIZATION MAPPING (Research Step 3)
    cohort_raw = llm_data.get("target_cohort", ["Student", "Staff"])
    if not isinstance(cohort_raw, list):
        cohort_raw = [cohort_raw]

    standardized_cohorts = set()
    mapping = {
        "student": "Student", "students": "Student", "undergraduate": "Student", "postgraduate": "Student",
        "staff": "Staff", "employee": "Staff", "academic": "Staff", "professional staff": "Staff",
        "researcher": "Staff", "external": "Public", "public": "Public"
    }
    
    for item in cohort_raw:
        clean_item = str(item).lower().strip()
        if clean_item in mapping:
            standardized_cohorts.add(mapping[clean_item])
    
    # Final Fallback
    final_cohorts = list(standardized_cohorts) if standardized_cohorts else ["Student", "Staff"]

    # Date Logic
    effective_date = llm_data.get("effective_date")
    review_date = llm_data.get("review_date")
    iso_eff = standardize_date(effective_date)
    iso_rev = standardize_date(review_date)

    enquiries = llm_data.get("enquiries_contact") or "University Administration"
    approval_body = llm_data.get("approval_authority") or "Academic Board"
    safe_escalation_contact = "Ask La Trobe or Governance and Policy at policy@latrobe.edu.au."

    # Chunking
    chunker = HierarchicalChunker()
    chunks = chunker.chunk(docling_document)
    chunks_payload = []
    
    for i, chunk in enumerate(chunks):
        text = chunk.text.strip()
        header_path = chunk.meta.headings if hasattr(chunk.meta, 'headings') and chunk.meta.headings else []
        breadcrumb = f"{document_title} > " + " > ".join(header_path) if header_path else document_title
        is_real_table = any("table" in str(getattr(item, "label", "")).lower() for item in getattr(chunk.meta, "doc_items", []))

        chunks_payload.append({
            "content": f"[{breadcrumb}]\n{text}", 
            "has_table": is_real_table, 
            "is_exception": any(word in text.lower() for word in ["unless", "except", "however", "provided that"]), 
            "document_title": document_title,
            "source_url": source_path, 
            "enquiries_contact": enquiries,
            "escalation_contact": safe_escalation_contact,
            "breadcrumb": breadcrumb,
            "document_summary": f"Policy regarding {document_title}.",
            "doc_type": doc_type,
            "category": ["Academic", "Policy Library"],
            "access_level": "Public",
            "target_cohort": final_cohorts, # USE THE STANDARDIZED LIST
            "campus_scope": ["All Campuses"],
            "document_id": document_id,  
            "approval_body": approval_body,
            "department_owner": enquiries,
            "status": llm_data.get("status", "Current"),
            "effective_date_iso": iso_eff,
            "review_date": review_date,
            "chunk_id": str(uuid.uuid4()),
            "chunk_index": i, 
            "chunk_type": "Table" if is_real_table else "Text"
        })
        
    return chunks_payload