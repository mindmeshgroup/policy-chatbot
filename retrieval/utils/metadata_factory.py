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
    """Uses LLM to extract metadata, focusing strictly on the authoritative table."""
    marker = "Status and Details Table"
    match = re.search(re.escape(marker), markdown_text, re.IGNORECASE)
    
    if match:
        analysis_text = markdown_text[match.start():match.start()+4000]
        print("    LLM focusing on  metadata block.")
    else:
        analysis_text = markdown_text[:2500] + "\n\n" + markdown_text[-3000:]

    prompt = f"""
    Strictly extract policy metadata into JSON:
    - "effective_date": Date policy commenced (labeled 'Effective' or 'Commencement').
    - "review_date": Labeled 'Review Date'.
    - "status": e.g. 'Current'.
    - "enquiries_contact": The responsible person or department listed for enquiries.
    - "approval_authority": The body that approved this.

    RULES:
    1. NEVER duplicate dates. If Effective Date is missing, return null. 
    2. Effective Date is usually 3 years BEFORE Review Date.
    
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
    
    # 1. Extract Title and generate document_id
    title_match = re.search(r'#+\s+(.*)', markdown_text)
    document_title = title_match.group(1).strip() if title_match else "Unknown Policy"
    document_id = hashlib.sha256(document_title.encode('utf-8')).hexdigest()[:12]
    doc_type = "Procedure" if "Procedure" in document_title else "Policy"

    # 2. Extract Metadata
    llm_data = extract_llm_metadata(markdown_text)
    effective_date = llm_data.get("effective_date")
    review_date = llm_data.get("review_date")

    # 3. Deterministic Regex Fallback
    date_regex = r'([0-9]{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+[0-9]{4})'
    if not effective_date or effective_date == review_date or "not specified" in str(effective_date).lower():
        match = re.search(rf"(?:Effective|Commencement|Approval)\s*Date[^\n\r]*?{date_regex}", markdown_text, re.IGNORECASE)
        if match:
            effective_date = match.group(1)

    # 4. Standardization & Final Verification
    iso_eff = standardize_date(effective_date)
    iso_rev = standardize_date(review_date)

    if iso_eff and iso_rev and iso_eff == iso_rev:
        print(f"     Warning: Duplicate dates detected for '{document_title}'. Forcing fallback.")
        effective_date = None
        iso_eff = None

    enquiries = llm_data.get("enquiries_contact") or "University Administration"
    approval_body = llm_data.get("approval_authority") or "Academic Board"
    
    # THE SAFETY OVERRIDE: Hardcoded safe escalation path for student queries
    safe_escalation_contact = "Ask La Trobe or Governance and Policy at policy@latrobe.edu.au."

    # 5. Chunking Logic
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
            "enquiries_contact": enquiries,               # FACTUAL: The specific author/advisor from the document
            "escalation_contact": safe_escalation_contact, # SAFEGUARD: The logical helpdesk for emergencies
            "breadcrumb": breadcrumb,
            "document_summary": f"Policy regarding {document_title}.",
            "doc_type": doc_type,
            "category": ["Academic", "Policy Library"],
            "access_level": "Public",
            "target_cohort": ["Student", "Staff"],
            "campus_scope": ["All Campuses"],
            "document_id": document_id,  
            "approval_body": approval_body,
            "department_owner": enquiries,
            "status": llm_data.get("status", "Current"),
            "effective_date": effective_date,
            "review_date": review_date,
            "effective_date_iso": iso_eff,
            "superseded_by": None,
            "chunk_id": str(uuid.uuid4()),
            "chunk_index": i, 
            "chunk_type": "Table" if is_real_table else "Text",
            "exception_scope": [],
            "parent_rule_id": None,
            "override_priority": 1
        })
        
    return chunks_payload