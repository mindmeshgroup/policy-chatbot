import hashlib
import json
import re
import os
import ollama
from datetime import datetime
from docling.chunking import HierarchicalChunker

# --- CONFIGURATION ---
EXTRACTOR_MODEL = "llama3"   

def standardize_date(date_str):
    if not date_str or str(date_str).lower() in ["none", "null", "unknown", "not specified", ""]: 
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

# ==========================================
# HYBRID WORKER 1: LLM EXTRACTION
# ==========================================
def extract_llm_cohort(scouted_text: str, document_title: str) -> dict:
    prompt = f"""
    You are an expert Data Security Classifier for La Trobe University.
    Analyze the policy text and output a JSON array of the intended audience.
    
    You MUST select from this exact list of 10 roles. Do not invent new roles:
    1. "Undergrad": Bachelor, diploma, standard coursework students.
    2. "Postgrad": Master's or advanced coursework students.
    3. "HDR": Higher Degree by Research, PhD, doctoral candidates.
    4. "International": Overseas students, visa holders.
    5. "Academic": Professors, lecturers, tutors, researchers.
    6. "Professional": Admin, IT, HR, management staff.
    7. "Casual": Sessional, hourly, or temporary workers.
    8. "Alumni": Graduates and former students.
    9. "Public": General public, community members.
    10. "Guest": Visitors, contractors, honorary staff.
    
    MAPPING RULES:
    - If it says "Staff" or "Employees", include ["Academic", "Professional", "Casual"].
    - If it says "Students", include ["Undergrad", "Postgrad", "HDR", "International"].
    - UNIVERSAL OVERRIDE: If the policy is about Safety, Privacy, Conduct, IT, Integrity, or applies to "everyone", you MUST output ALL 10 roles.
    
    Document Title: {document_title}
    Text: {scouted_text[:2500]}
    
    Output strictly valid JSON exactly like this: {{"target_cohort": ["Role1", "Role2"]}}
    """
    try:
        response = ollama.chat(
            model=EXTRACTOR_MODEL, 
            messages=[{'role': 'user', 'content': prompt}], 
            format='json', 
            options={'temperature': 0.0, 'num_ctx': 2048},
            keep_alive="5m"
        )
        return json.loads(response['message']['content'])
    except Exception as e:
        print(f"      [!] Ollama Extraction Error: {e}")
        return {} 

# ==========================================
# HYBRID WORKER 2: DETERMINISTIC FAILSAFE
# ==========================================
def _get_target_cohort(scouted_context, document_title):
    # 1. Ask the Upgraded LLM
    llm_data = extract_llm_cohort(scouted_context, document_title)
    cohort_raw = llm_data.get("target_cohort", [])
    if not isinstance(cohort_raw, list): cohort_raw = [cohort_raw]

    ALL_ROLES = ["Undergrad", "Postgrad", "HDR", "International", "Academic", "Professional", "Casual", "Alumni", "Public", "Guest"]
    
    # 2. Clean LLM Output
    final_set = set()
    for tag in cohort_raw:
        clean_tag = str(tag).strip().title()
        if clean_tag in ALL_ROLES:
            final_set.add(clean_tag)

    # 3. The Taxonomy Failsafe (Catches what the LLM misses)
    text_to_scan = (document_title + " " + scouted_context).lower()
    
   # Define title_lower early so all boundary checks can use it
    title_lower = document_title.lower()

    # UNIVERSAL OVERRIDE (FIXED: We use update() instead of return so it keeps reading)
    UNIVERSAL_KEYWORDS = ["all persons", "university community", "everyone", "individuals", "privacy", "safety", "conduct", "whistleblower", "compliance", "facilities", "integrity"]
    if any(term in text_to_scan for term in UNIVERSAL_KEYWORDS):
        final_set.update(ALL_ROLES)

    # Expand tags based on heavy keywords
    STUDENT_KEYWORDS = ["student", "learner", "candidate", "undergrad", "admission", "enrollment", "coursework", "exam", "assessment", "grade", "tuition", "scholarship"]
    if any(term in text_to_scan for term in STUDENT_KEYWORDS):
        final_set.update(["Undergrad", "Postgrad", "HDR", "International"])
        
    HDR_KEYWORDS = ["hdr", "doctoral", "phd", "research degree", "thesis", "graduate research"]
    if any(term in text_to_scan for term in HDR_KEYWORDS):
        final_set.update(["HDR", "Academic"])
        
    STAFF_KEYWORDS = ["staff", "employee", "workplace", "academic", "professional", "casual", "salary", "employment", "leave", "recruitment", "manager", "overtime"]
    if any(term in text_to_scan for term in STAFF_KEYWORDS):
        final_set.update(["Academic", "Professional", "Casual"])

    # --- REFINED HR BOUNDARY FIX ---
    HR_TITLES = [
        "employment", "termination of employment", "remuneration", 
        "staff leave", "staff workload", "staff probation", 
        "performance review", "flexible working", "working from home", 
        "staff recruitment"
    ]
    
    if any(k in title_lower for k in HR_TITLES):
        final_set.difference_update(["Undergrad", "Postgrad", "HDR", "International", "Alumni", "Public", "Guest"])
    # ---------------------------

    # 4. Strict Title Discards (Prevents undergrads from seeing PhD policies)
    if any(k in title_lower for k in ["graduate", "postgraduate", "hdr", "doctoral", "masters"]):
        final_set.difference_update(["Undergrad", "Alumni", "Public", "Guest"])
        
    if "undergraduate" in title_lower:
        final_set.difference_update(["Postgrad", "HDR"])

    # 5. Ultimate Failsafe (Defaults to open if totally blank)
    if not final_set:
        return ALL_ROLES.copy()

    # Ensure Academics can always see student academic policies
    if any(role in final_set for role in ["Undergrad", "Postgrad", "HDR", "International"]): 
        final_set.add("Academic")

    return list(final_set)

# ==========================================
# THE ROUTER (STRATEGY PATTERN)
# ==========================================
def extract_metadata_and_chunk(docling_document, source_path: str):
    chunker = HierarchicalChunker()
    chunks = list(chunker.chunk(docling_document))
    
    if not chunks:
        return []

    # 1. Route based on document type
    is_pdf = source_path.lower().endswith('.pdf')
    
    if is_pdf:
        metadata = _extract_pdf_metadata(chunks, source_path)
    else:
        metadata = _extract_web_metadata(chunks, source_path)

    # 2. Shared Logic: LLM Cohort Extraction & ABAC Ceiling
    global_cohorts = _get_target_cohort(metadata["scouted_context"], metadata["document_title"])

    # 3. Shared Logic: Payload Assembly & Exception Tagging
    return _assemble_final_payload(chunks, source_path, metadata, global_cohorts)


# ==========================================
# SPECIALIST 1: WEB EXTRACTOR
# ==========================================
def _extract_web_metadata(chunks, source_path):
    import os
    import re

    document_title = "Unknown Policy"
    for chunk in chunks[:10]:
        if hasattr(chunk.meta, 'headings') and chunk.meta.headings:
            candidate = chunk.meta.headings[0]
            if "section 99" not in candidate.lower() and "status and details" not in candidate.lower():
                document_title = candidate
                break
                
    safe_top = "\n".join([c.text for c in chunks[:5]])
    safe_bottom = "\n".join([c.text for c in chunks[-5:]]) if len(chunks) > 5 else ""
    
    scouted_middle = []
    valid_keywords = ["scope", "audience", "application"]
    for chunk in chunks[5:-5]:
        text_lower = chunk.text.lower().strip()
        headers = [h.lower() for h in getattr(chunk.meta, 'headings', [])] if hasattr(chunk.meta, 'headings') else []
        if any(keyword in h for h in headers for keyword in valid_keywords) or bool(re.match(r'^(section \d+ - )?(scope|audience|application)', text_lower)):
            scouted_middle.append(chunk.text)
            if len(scouted_middle) >= 3: break

    scouted_context = f"{safe_top}\n" + "\n".join(scouted_middle) + f"\n{safe_bottom}"

    eff_match = re.search(r'Effective Date.*?(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}|\d{4}-\d{2}-\d{2})', scouted_context, re.IGNORECASE)
    rev_match = re.search(r'Review Date.*?(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}|\d{4}-\d{2}-\d{2})', scouted_context, re.IGNORECASE)
    
    mgr_match = re.search(r'Responsible Manager.*?\[(.*?)\]\s*\(mailto:(.*?)\)', scouted_context, re.IGNORECASE)
    
    # THE ULTIMATE ENQUIRIES FIX
    final_enq_name = "University Administration"
    final_enq_email = ""
    
    enq_match_email = re.search(r'Enquiries Contact.*?=\s*\[(.*?)\]\s*\(mailto:(.*?)\)', scouted_context, re.IGNORECASE)
    if enq_match_email:
        final_enq_name = enq_match_email.group(1).strip()
        final_enq_email = enq_match_email.group(2).strip()
    else:
        enq_match_plain = re.search(r'Enquiries Contact.*?=\s*(?:\[)?([A-Za-z\,\s\-\&]+?)(?:\]|\n|\(|\.|$)', scouted_context, re.IGNORECASE)
        if not enq_match_plain:
             enq_match_plain = re.search(r'Enquiries Contact[\s\n:]+(?:\[)?([A-Za-z\,\s\-\&]+?)(?:\]|\n|\(|\.|$)', scouted_context, re.IGNORECASE)
        if enq_match_plain:
            final_enq_name = enq_match_plain.group(1).strip()

    # THE VICE-CHANCELLOR FIX (Added hyphen to regex)
    appr_match = re.search(r'Approval Authority.*?=\s*([A-Za-z\s\-]+)', scouted_context, re.IGNORECASE)
    status_match = re.search(r'Status, 1 = \[?(.*?)\]?(\(http|\.)', scouted_context, re.IGNORECASE)

    return {
        "document_title": document_title,
        "scouted_context": scouted_context,
        "iso_eff": standardize_date(eff_match.group(1)) if eff_match else "1970-01-01",
        "iso_rev": standardize_date(rev_match.group(1)) if rev_match else "2099-12-31",
        "manager_dict": {"name": mgr_match.group(1).strip(), "email": mgr_match.group(2).strip()} if mgr_match else {"name": "Executive Board", "email": ""},
        "enquiries_dict": {"name": final_enq_name, "email": final_enq_email, "phone": ""},
        "final_approval": appr_match.group(1).strip() if appr_match else "Academic Board",
        "final_status": status_match.group(1).strip() if status_match else "Current"
    }

# ==========================================
# SPECIALIST 2: PDF EXTRACTOR
# ==========================================
def _extract_pdf_metadata(chunks, source_path):
    import os
    import re
    
    document_title = "Unknown Policy"
    
    for chunk in chunks[:10]:
        if hasattr(chunk.meta, 'headings') and chunk.meta.headings:
            candidate = chunk.meta.headings[0].strip()
            candidate_lower = candidate.lower()
            
            if "section 99" not in candidate_lower and "status and details" not in candidate_lower and "section 1" not in candidate_lower:
                if not re.match(r'^[\(\d]', candidate) and not candidate_lower.startswith("part"):
                     if len(candidate.split()) > 2 or any(word in candidate_lower for word in ["policy", "procedure", "standard", "guideline"]):
                        document_title = candidate
                        break
                
    if document_title == "Unknown Policy" or "Section" in document_title or document_title.startswith("("):
        base_name = os.path.basename(source_path)
        document_title = re.sub(r'\.pdf|\.html', '', base_name, flags=re.IGNORECASE).replace('-', ' ').replace('_', ' ').title()
        document_title = re.sub(r'\s+', ' ', document_title).strip() 

    bottom_text = " ".join([c.text for c in chunks[-10:]])
    flat_bottom = re.sub(r'[\n\|\"\,]+', ' ', bottom_text)
    flat_bottom = re.sub(r'\s+', ' ', flat_bottom) 
    
    all_dates = re.findall(r'\b\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}\b|\b\d{4}-\d{2}-\d{2}\b', flat_bottom)
    iso_eff = standardize_date(all_dates[0]) if len(all_dates) > 0 else "1970-01-01"
    iso_rev = standardize_date(all_dates[1]) if len(all_dates) > 1 else "2099-12-31"

    appr_match = re.search(r'Approval Authority\s+([A-Za-z\s\-\(\)]+?)\s+(?:Approval Date|Expiry Date|Responsible Manager)', flat_bottom, re.IGNORECASE)
    final_approval = appr_match.group(1).strip() if appr_match else "Academic Board"
    
    mgr_match = re.search(r'Responsible Manager.*?\s+([A-Za-z\s\-\(\)]+?)\s+(?:Enquiries|Glossary|This policy)', flat_bottom, re.IGNORECASE)
    final_mgr = mgr_match.group(1).strip() if mgr_match else "Executive Board"
    
    enq_match = re.search(r'Enquiries Contact\s+([A-Za-z\s\-\(\)]+?)\s+(?:Glossary|This policy|Definitions)', flat_bottom, re.IGNORECASE)
    final_enq = enq_match.group(1).strip() if enq_match else "University Administration"

    status_match = re.search(r'Status\s+(Current|Historic|Future)', flat_bottom, re.IGNORECASE)
    final_status = status_match.group(1).strip() if status_match else "Current"

    safe_top = "\n".join([c.text for c in chunks[:5]])
    safe_bottom = "\n".join([c.text for c in chunks[-5:]]) if len(chunks) > 5 else ""
    scouted_middle = []
    
    for chunk in chunks[5:-5]:
        text_lower = chunk.text.lower().strip()
        headers = [h.lower() for h in getattr(chunk.meta, 'headings', [])] if hasattr(chunk.meta, 'headings') else []
        if any(keyword in h for h in headers for keyword in ["scope", "audience", "application"]) or bool(re.match(r'^(section \d+ - )?(scope|audience|application)', text_lower)):
            scouted_middle.append(chunk.text)
            if len(scouted_middle) >= 3: break

    return {
        "document_title": document_title,
        "scouted_context": f"{safe_top}\n" + "\n".join(scouted_middle) + f"\n{safe_bottom}",
        "iso_eff": iso_eff,
        "iso_rev": iso_rev,
        "manager_dict": {"name": final_mgr, "email": ""},
        "enquiries_dict": {"name": final_enq, "email": "", "phone": ""},
        "final_approval": final_approval,
        "final_status": final_status
    }

# ==========================================
# PAYLOAD ASSEMBLY
# ==========================================
def _assemble_final_payload(chunks, source_path, metadata, global_cohorts):
    document_title = metadata["document_title"]
    document_id = hashlib.sha256(document_title.encode('utf-8')).hexdigest()[:12]
    doc_type = "Procedure" if "Procedure" in document_title else "Policy"
    strict_exception_pattern = re.compile(r'\b(unless|except|provided that|notwithstanding|subject to|exempt from|waive the requirement|does not apply to|exception|exclusion)\b', re.IGNORECASE)

    chunks_payload = []
    for i, chunk in enumerate(chunks):
        text = chunk.text.strip()
        header_path = chunk.meta.headings if hasattr(chunk.meta, 'headings') and chunk.meta.headings else []
        breadcrumb = f"{document_title} > " + " > ".join(header_path) if header_path else document_title
        breadcrumb_lower = breadcrumb.lower()
        is_real_table = any("table" in str(getattr(item, "label", "")).lower() for item in getattr(chunk.meta, "doc_items", []))

        chunk_is_exception = any(word in breadcrumb_lower for word in ["exclusion", "exemption", "exception", "waiver"]) or bool(strict_exception_pattern.search(text))
        chunk_specific_cohorts = set(global_cohorts)
        
        if any(word in breadcrumb_lower for word in ["staff", "admin", "employee"]): chunk_specific_cohorts.update(["Academic", "Professional"])
        if any(word in breadcrumb_lower for word in ["student", "candidate", "learner"]): chunk_specific_cohorts.update(["Undergrad", "Postgrad", "HDR", "International"])
        if "hdr" in breadcrumb_lower or "doctoral" in breadcrumb_lower: chunk_specific_cohorts.update(["HDR", "Academic"])

        chunks_payload.append({
            "content": f"[{breadcrumb}]\n{text}", 
            "has_table": is_real_table, 
            "is_exception": chunk_is_exception, 
            "document_title": document_title,
            "source_url": source_path, 
            "enquiries_contact": metadata["enquiries_dict"],
            "responsible_manager": metadata["manager_dict"],
            "escalation_contact": "Ask La Trobe or Governance and Policy at policy@latrobe.edu.au.",
            "breadcrumb": breadcrumb,
            "document_summary": f"Policy regarding {document_title}.",
            "doc_type": doc_type,
            "category": "Academic Policy Library",
            "access_level": "Public",
            "target_cohort": list(chunk_specific_cohorts), 
            "campus_scope": ["All Campuses"],
            "document_id": document_id,  
            "approval_body": metadata["final_approval"], 
            "department_owner": metadata["enquiries_dict"],
            "status": metadata["final_status"],
            "effective_date_iso": metadata["iso_eff"],
            "review_date": metadata["iso_rev"],
            "chunk_id": hashlib.md5(f"{source_path}_chunk_{i}".encode('utf-8')).hexdigest(),
            "chunk_index": i, 
            "chunk_type": "Table" if is_real_table else "Text"
        })
        
    return chunks_payload