import hashlib
import json
import re
import ollama
from datetime import datetime
from docling.chunking import HierarchicalChunker

# --- CONFIGURATION ---
EXTRACTOR_MODEL = "llama3"   

def standardize_date(date_str):
    """Handles  Year-Only fallbacks."""
    if not date_str or str(date_str).lower() in ["none", "null", "unknown", "not specified"]: 
        return None
    try:
        clean_date = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', str(date_str)).strip()
        for fmt in ["%d %B %Y", "%d %b %Y", "%Y-%m-%d", "%d/%m/%Y", "%Y"]:
            try:
                dt = datetime.strptime(clean_date, fmt)
                if fmt == "%Y": return dt.strftime("%Y-01-01")
                return dt.strftime("%Y-%m-%d")
            except ValueError: 
                continue
        return None
    except Exception: 
        return None

def extract_global_metadata(scouted_text: str) -> dict:
    """Uses Ollama with Synthetic Few-Shot examples to extract data exactly ONCE per document."""
    prompt = f"""
    Strictly extract policy metadata into JSON.
    - "effective_date": Format strictly as YYYY-MM-DD.
    - "review_date": Format strictly as YYYY-MM-DD.
    - "status": e.g. 'Current'.
    - "enquiries_contact": The responsible department.
    - "approval_authority": The body that approved this.
    - "target_cohort": Return an array using ONLY: "Undergrad", "Postgrad", "HDR", "International", "Academic", "Professional", "Casual", "Alumni", "Public", "Guest".
    
    SYNTHETIC EXAMPLES:
    Excerpt: "This procedure outlines the payroll schedule for all casual and full-time faculty."
    Output: {{"target_cohort": ["Academic", "Professional", "Casual"]}}
    
    Excerpt: "This policy sets the grading curve for undergraduate and postgraduate assessments."
    Output: {{"target_cohort": ["Undergrad", "Postgrad", "Academic"]}}
    
    Excerpt: "This applies to all members of the university community."
    Output: {{"target_cohort": ["Undergrad", "Postgrad", "HDR", "International", "Academic", "Professional", "Casual", "Alumni", "Public", "Guest"]}}

    RULES: 
    1. Only return JSON. If a field is missing, return null.
    2. A policy MUST have an audience. If no specific restricted audience is mentioned in the text, you MUST default to the universal array (all 10 roles). DO NOT output an empty array.
    
    Text: {scouted_text}
    """
    try:
        response = ollama.chat(
            model=EXTRACTOR_MODEL, 
            messages=[{'role': 'user', 'content': prompt}], 
            format='json', 
            options={'temperature': 0.0},
            keep_alive=0 
        )
        return json.loads(response['message']['content'])
    except Exception as e:
        print(f"      [!] Ollama Extraction Error: {e}")
        return {} 

def extract_metadata_and_chunk(docling_document, source_path: str):
    # 1. STRUCTURAL PARSING (Docling)
    chunker = HierarchicalChunker()
    chunks = list(chunker.chunk(docling_document))
    
    document_title = chunks[0].meta.headings[0] if chunks and chunks[0].meta.headings else "Unknown Policy"
    document_id = hashlib.sha256(document_title.encode('utf-8')).hexdigest()[:12]
    doc_type = "Procedure" if "Procedure" in document_title else "Policy"

    # 2. UPGRADED STRUCTURAL SCOUTING (Sub-string + Text Pattern Matching)
    scouted_context = ""
    valid_keywords = ["scope", "audience", "application", "status and details"]
    
    for chunk in chunks:
        # Check Docling Headers
        headers = [h.lower() for h in (chunk.meta.headings if hasattr(chunk.meta, 'headings') and chunk.meta.headings else [])]
        is_real_table = any("table" in str(getattr(item, "label", "")).lower() for item in getattr(chunk.meta, "doc_items", []))
        has_target_header = any(keyword in h for h in headers for keyword in valid_keywords)
        
        # Safety: Check raw text in case Docling failed to mark heading
        text_lower = chunk.text.lower().strip()
        has_target_text = bool(re.match(r'^(section \d+ - )?(scope|audience|application)', text_lower))
        
        if has_target_header or is_real_table or has_target_text:
            scouted_context += chunk.text + "\n"
            
    if not scouted_context.strip():
        print(f"      [!] Scouting missed headers. Falling back to expanded top of document.")
        scouted_context = docling_document.export_to_markdown()[:3000]

    # 3. OLLAMA IN-CONTEXT EXTRACTION
    llm_data = extract_global_metadata(scouted_context)
    
    # 4. DETERMINISTIC ROLE MAPPING + SAFETY NET
    cohort_raw = llm_data.get("target_cohort", [])
    if not isinstance(cohort_raw, list): cohort_raw = [cohort_raw]

    ALL_ROLES = ["Undergrad", "Postgrad", "HDR", "International", "Academic", "Professional", "Casual", "Alumni", "Public", "Guest"]
    ROLE_EXPANSION_MAP = {
        "all": ALL_ROLES, "universal": ALL_ROLES, "university community": ALL_ROLES,
        "staff and students": ALL_ROLES, "all members": ALL_ROLES,
        "student": ["Undergrad", "Postgrad", "HDR", "International"],
        "staff": ["Academic", "Professional", "Casual"],
        "undergraduate": ["Undergrad"], "postgraduate": ["Postgrad"],
        "researcher": ["HDR", "Academic"], 
        "higher degree by research": ["HDR", "Academic"],
        "hdr": ["HDR", "Academic"],
        "academic": ["Academic"],
        "professional": ["Professional"], "public": ["Public", "Guest"]
    }

    final_set = set()
    for tag in cohort_raw:
        clean_tag = str(tag).lower().strip()
        final_set.update(ROLE_EXPANSION_MAP.get(clean_tag, [str(tag).strip().title()]))

    # --- DETERMINISTIC SAFETY NET ---
    scouted_lower = scouted_context.lower()
    
    if "student" in scouted_lower or "learner" in scouted_lower:
        final_set.update(["Undergrad", "Postgrad", "HDR", "International"])
        
    if "hdr" in scouted_lower or "higher degree by research" in scouted_lower or "doctoral" in scouted_lower:
        final_set.update(["HDR", "Academic"])
        
    if "staff" in scouted_lower or "employee" in scouted_lower:
        final_set.update(["Academic", "Professional", "Casual"])
        
    if "university community" in scouted_lower or "all members" in scouted_lower:
        final_set.update(ALL_ROLES)

    # Academic Inheritance Rule
    if any(role in final_set for role in ["Undergrad", "Postgrad", "HDR", "International"]):
        final_set.add("Academic")

    global_cohorts = [r for r in final_set if r in ALL_ROLES]
    if not global_cohorts: 
        print(f"      [QUARANTINE ALERT] No valid roles. '{document_title}' hidden.")
        global_cohorts = ["Quarantined"]

    # Normalize Dates
    iso_eff = standardize_date(llm_data.get("effective_date"))
    iso_rev = standardize_date(llm_data.get("review_date"))
    enquiries = llm_data.get("enquiries_contact") or "University Administration"

    # 5. STRICT EXCEPTION DETECTION (CRAG Upgrade)
    strict_exception_pattern = re.compile(
        r'\b(unless|except|provided that|notwithstanding|subject to|exempt from|waive the requirement|does not apply to)\b',
        re.IGNORECASE
    )

    # 6. METADATA INHERITANCE & SECTION TRACKING
    chunks_payload = []
    for i, chunk in enumerate(chunks):
        text = chunk.text.strip()
        header_path = chunk.meta.headings if hasattr(chunk.meta, 'headings') and chunk.meta.headings else []
        breadcrumb = f"{document_title} > " + " > ".join(header_path) if header_path else document_title
        breadcrumb_lower = breadcrumb.lower()
        is_real_table = any("table" in str(getattr(item, "label", "")).lower() for item in getattr(chunk.meta, "doc_items", []))

        # --- NEW CRAG TAGGING LOGIC ---
        # 1. Structural Audit: Checks the Docling breadcrumbs for explicit override sections
        is_structural_exception = any(word in breadcrumb_lower for word in ["exclusion", "exemption", "exception", "waiver", "special consideration"])
        # 2. Linguistic Audit: Checks the text for strict override markers
        is_text_exception = bool(strict_exception_pattern.search(text))
        
        chunk_is_exception = is_structural_exception or is_text_exception
        # ------------------------------

        chunk_specific_cohorts = set(global_cohorts)
        if "Quarantined" not in global_cohorts:
            if any(word in breadcrumb_lower for word in ["staff", "admin", "employee", "processing"]):
                chunk_specific_cohorts.update(["Academic", "Professional"])
            if any(word in breadcrumb_lower for word in ["student", "candidate", "learner"]):
                chunk_specific_cohorts.update(["Undergrad", "Postgrad", "HDR", "International"])
            if "hdr" in breadcrumb_lower or "doctoral" in breadcrumb_lower:
                chunk_specific_cohorts.update(["HDR", "Academic"])

        chunk_final_roles = list(chunk_specific_cohorts) if "Quarantined" not in global_cohorts else ["Quarantined"]

        chunks_payload.append({
            "content": f"[{breadcrumb}]\n{text}", 
            "has_table": is_real_table, 
            "is_exception": chunk_is_exception, 
            "document_title": document_title,
            "source_url": source_path, 
            "enquiries_contact": enquiries,
            "escalation_contact": "Ask La Trobe or Governance and Policy at policy@latrobe.edu.au.",
            "breadcrumb": breadcrumb,
            "document_summary": f"Policy regarding {document_title}.",
            "doc_type": doc_type,
            "category": ["Academic", "Policy Library"],
            "access_level": "Public",
            "target_cohort": chunk_final_roles, 
            "campus_scope": ["All Campuses"],
            "document_id": document_id,  
            "approval_body": llm_data.get("approval_authority") or "Academic Board",
            "department_owner": enquiries,
            "status": llm_data.get("status", "Current"),
            "effective_date_iso": iso_eff,
            "review_date": iso_rev,
            "chunk_id": hashlib.md5(f"{source_path}_chunk_{i}".encode('utf-8')).hexdigest(),
            "chunk_index": i, 
            "chunk_type": "Table" if is_real_table else "Text"
        })
        
    return chunks_payload