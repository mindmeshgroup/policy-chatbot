import hashlib
import json
import re
import os
import ollama
import spacy
from datetime import datetime
from docling_core.transforms.chunker import HierarchicalChunker
from urllib.parse import urlparse, parse_qs
# --- CONFIGURATION ---
EXTRACTOR_MODEL = "llama3.2"  

try:
    print("Loading spaCy NLP model for semantic chunking...")
    nlp = spacy.load("en_core_web_sm")
except OSError:
    print("[WARNING] spaCy model 'en_core_web_sm' not found. Run: python -m spacy download en_core_web_sm")
    nlp = None # Fallback just in case
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
    Analyze the policy text and output a JSON object containing the title and the intended audience.
    
    1. IDENTIFY TITLE:
    - Extract the official legal name of the policy (e.g., 'Intellectual Property Policy').
    - You MUST ignore website navigation text like 'Jump to Content', 'Jump to Navigation', 'Menu', or 'Search'.
    - If you cannot find a clear title in the text, use: "{document_title}"

    2. IDENTIFY ROLES:
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
    - UNIVERSAL OVERRIDE: If the policy is about general Safety, Privacy, IT, or applies to "everyone", you MUST output ALL 10 roles. (NOTE: Do NOT apply this to specific student 'misconduct' procedures).
    
    Current File Hint: {document_title}
    Text: {scouted_text[:3000]}
    
    Output strictly valid JSON exactly like this: 
    {{"document_title": "Actual Policy Name", "target_cohort": ["Role1", "Role2"]}}
    """
    try:
        response = ollama.chat(
            model=EXTRACTOR_MODEL, 
            messages=[{'role': 'user', 'content': prompt}], 
            format='json', 
            options={'temperature': 0.0, 'num_ctx': 4096}, # Increased context window for title scanning
            keep_alive="5m"
        )
        return json.loads(response['message']['content'])
    except Exception as e:
        print(f"      [!] Ollama Extraction Error: {e}")
        return {}

# ==========================================
# HYBRID WORKER 2: DETERMINISTIC FAILSAFE
# ==========================================
# Updated signature to accept the roles already found by the LLM
def _get_target_cohort(scouted_context, document_title, llm_roles=None):
    
    # 1. Use the roles passed from the router instead of calling the LLM again
    cohort_raw = llm_roles if llm_roles is not None else []
    if not isinstance(cohort_raw, list): cohort_raw = [cohort_raw]

    ALL_ROLES = ["Undergrad", "Postgrad", "HDR", "International", "Academic", "Professional", "Casual", "Alumni", "Public", "Guest"]
    
    # 2. Clean LLM Output
    final_set = set()
    for tag in cohort_raw:
        clean_tag = str(tag).strip().title()
        if clean_tag in ALL_ROLES:
            final_set.add(clean_tag)

    # 3. The Taxonomy Failsafe (Catches what the LLM misses)
    # [Rest of your logic remains identical...]
    text_to_scan = (document_title + " " + scouted_context).lower()
    title_lower = document_title.lower()

    # UNIVERSAL OVERRIDE 
    UNIVERSAL_KEYWORDS = ["all persons", "university community", "everyone", "individuals", "privacy", "safety", "conduct", "whistleblower", "compliance", "facilities", "integrity"]
    if any(re.search(rf"\b{term}\b", text_to_scan) for term in UNIVERSAL_KEYWORDS):
        final_set.update(ALL_ROLES)

    # Expand tags based on heavy keywords 
    STUDENT_KEYWORDS = ["student", "learner", "candidate", "undergrad", "admission", "enrollment", "coursework", "exam", "assessment", "grade", "tuition", "scholarship"]
    if any(re.search(rf"\b{term}\b", text_to_scan) for term in STUDENT_KEYWORDS):
        final_set.update(["Undergrad", "Postgrad", "HDR", "International"])
        
    HDR_KEYWORDS = ["hdr", "doctoral", "phd", "research degree", "thesis", "graduate research"]
    if any(re.search(rf"\b{term}\b", text_to_scan) for term in HDR_KEYWORDS):
        final_set.update(["HDR", "Academic"])
        
    STAFF_KEYWORDS = ["staff", "employee", "workplace", "academic", "professional", "casual", "salary", "employment", "leave", "recruitment", "manager", "overtime"]
    if any(re.search(rf"\b{term}\b", text_to_scan) for term in STAFF_KEYWORDS):
        final_set.update(["Academic", "Professional", "Casual"])

    # HR BOUNDARY FIX
    HR_TITLES = [
        "employment", "termination of employment", "remuneration", 
        "staff leave", "staff workload", "staff probation", 
        "performance review", "flexible working", "working from home", 
        "staff recruitment", "outside work", "conflict of interest" 
    ]
    if any(k in title_lower for k in HR_TITLES):
        final_set.difference_update(["Undergrad", "Postgrad", "HDR", "International", "Alumni", "Public", "Guest"])

    # Strict Title Discards
    if any(k in title_lower for k in ["graduate", "postgraduate", "hdr", "doctoral", "masters", "higher degree", "research degree"]):
        final_set.difference_update(["Undergrad", "Alumni", "Public", "Guest"])
        
    if "undergraduate" in title_lower:
        final_set.difference_update(["Postgrad", "HDR"])

    # Ultimate Failsafe
    if not final_set:
        return ALL_ROLES.copy()

    # Academic Inheritance Rule
    if any(role in final_set for role in ["Undergrad", "Postgrad", "HDR", "International"]): 
        final_set.add("Academic")

    return list(final_set)
def _consolidate_semantic_chunks(raw_chunks):
    """
    Merges fragmented text chunks (<100 chars, bullet points, broken sentences) 
    into meaningful paragraphs using a Hybrid approach (Regex + spaCy NLP)
    to preserve semantic context for the LLM.
    """
    if not raw_chunks:
        return []

    chunks = []
    current_chunk = raw_chunks[0]
    
    # Layer 1: Fast Regex Patterns
    list_marker_pattern = re.compile(r'^(\d+[\.\)]|\-|\*|\([a-z]\))\s+') 
    sentence_end_pattern = re.compile(r'[\.\?\!\:]\s*$') 
    
    for nxt in raw_chunks[1:]:
        text_current = current_chunk.text.strip()
        text_next = nxt.text.strip()
        
        # Avoid index errors on empty chunks
        if not text_next:
            continue
            
        # 1. Regex: Fragment or Bullet List
        is_fragment = len(text_current) < 100 or len(text_next) < 100
        is_list_item = bool(list_marker_pattern.match(text_next))
        is_broken_sentence = not bool(sentence_end_pattern.search(text_current))
        
        # 2. NLP: Grammatical Cohesion Check (Only run if Regex doesn't immediately catch it)
        is_grammatical_continuation = False
        if nlp and not (is_fragment or is_list_item):
            # Parse the first few words of the next chunk to see if it relies on the previous sentence
            doc = nlp(text_next[:50]) 
            if len(doc) > 0:
                first_token = doc[0]
                # If it starts with a conjunction (and, but, because) or a pronoun
                if first_token.pos_ in ["CCONJ", "SCONJ", "PRON"]:
                    is_grammatical_continuation = True
                # If it starts with a lowercase letter (fallback for bad PDF breaks)
                elif first_token.is_lower:
                    is_grammatical_continuation = True

        # If ANY layer flags the chunk as broken, merge it!
        if is_fragment or is_list_item or is_broken_sentence or is_grammatical_continuation:
            current_chunk.text = f"{text_current}\n{text_next}"
            
            # Preserve tables during the merge
            if hasattr(nxt.meta, 'doc_items') and nxt.meta.doc_items:
                if getattr(current_chunk.meta, 'doc_items', None) is None:
                    current_chunk.meta.doc_items = []
                current_chunk.meta.doc_items.extend(nxt.meta.doc_items)
        else:
            chunks.append(current_chunk)
            current_chunk = nxt
            
    if current_chunk:
        chunks.append(current_chunk)
        
    return chunks
# ==========================================
# THE ROUTER (STRATEGY PATTERN)
# ==========================================
def extract_metadata_and_chunk(docling_document, source_path: str):
    chunker = HierarchicalChunker()
    raw_chunks = list(chunker.chunk(docling_document))
    if not raw_chunks: return []

    # 1. Consolidate fragments first
    chunks = _consolidate_semantic_chunks(raw_chunks)

    # 2. Extract initial scouted context (first 10 chunks) for the LLM to scan
    scouted_context = "\n".join([c.text for c in chunks[:10]])

    # 3. Layer A: Ask the LLM to identify the title and cohort
    filename_hint = os.path.basename(source_path).replace('-', ' ').title()
    llm_data = extract_llm_cohort(scouted_context, filename_hint)
    
    # Extract the two fields your prompt specifically returns
    document_title = llm_data.get("document_title", "Unknown Policy")
    llm_target_cohort = llm_data.get("target_cohort", [])

    # 4. Layer B: Structural/Regex Fallback (If LLM gave junk like 'Jump to Navigation')
    if "jump" in document_title.lower() or "menu" in document_title.lower() or document_title == "Unknown Policy":
        for line in scouted_context.split('\n'):
            clean = line.strip()
            # If it's a reasonable length and doesn't contain UI noise symbols
            if 10 < len(clean) < 150 and not any(x in clean for x in ['#', '/', '>', '|', '\\']):
                if "la trobe" not in clean.lower() and "menu" not in clean.lower():
                    document_title = clean.title()
                    break

    # 5. Layer C: Deterministic URL Fallback (The absolute failsafe)
    if "jump" in document_title.lower() or document_title == "Unknown Policy":
        parsed_url = urlparse(source_path)
        query_params = parse_qs(parsed_url.query)
        document_title = f"Policy ID: {query_params['id'][0]}" if 'id' in query_params else filename_hint

    # 6. Route to Specialist Extractors for Dates/Managers
    is_pdf = source_path.lower().endswith('.pdf')
    
    # PASS the document_title we just found into the specialists so they don't overwrite it
    if is_pdf:
        metadata = _extract_pdf_metadata(chunks, source_path)
    else:
        metadata = _extract_web_metadata(chunks, source_path)

    # FORCE the high-quality title into the final metadata object
    metadata["document_title"] = document_title

    # 7. Shared Logic: ABAC Ceiling & Final Assembly
    # Pass the llm_target_cohort directly to the failsafe worker to validate against your mapping rules
    global_cohorts = _get_target_cohort(metadata["scouted_context"], document_title, llm_target_cohort)
    
    return _assemble_final_payload(chunks, source_path, metadata, global_cohorts)

# ==========================================
# SPECIALIST 1: WEB EXTRACTOR
# ==========================================
def _extract_web_metadata(chunks, source_path):
    # 1. Deeper scan for the title in Docling headers
    document_title = "Unknown Policy"
    
    # We look through the first 20 chunks to get past the Section 99 metadata
    for chunk in chunks[:20]:
        if hasattr(chunk.meta, 'headings') and chunk.meta.headings:
            # Grab the first heading available
            candidate = chunk.meta.headings[0].strip()
            candidate_lower = candidate.lower()
            
            # THE FILTER: Ignore the metadata header and generic sections
            if "status and details" not in candidate_lower and not candidate_lower.startswith(("section", "part")):
                document_title = candidate
                break
                
    # --- THE STRUCTURAL RESCUE (If headings failed) ---
    if document_title == "Unknown Policy" and chunks:
        # Combine the top portion of the document (Top 15 chunks)
        top_text = "\n".join([c.text for c in chunks[:15]])
        for line in top_text.split('\n'):
            line_clean = line.strip()
            line_lower = line_clean.lower()
            
            # Skip noise: empty, breadcrumbs, branding, or UI buttons
            if not line_clean or any(char in line_clean for char in ['/', '>', '|', '\\']): 
                continue
            if "la trobe university" in line_lower or line_lower in ["menu", "hide navigation", "view document"]:
                continue
            if line_lower.startswith(("section ", "part ", "status and details")): 
                continue
                
            # Valid title length check
            if 5 < len(line_clean) < 150:
                document_title = line_clean.title()
                break

    # THE URL FALLBACK (Last Resort)
    if document_title == "Unknown Policy":
        if source_path.startswith("http"):
            parsed_url = urlparse(source_path)
            query_params = parse_qs(parsed_url.query)
            document_title = f"Policy ID: {query_params['id'][0]}" if 'id' in query_params else (os.path.basename(parsed_url.path) or "Web Document")
        else:
            document_title = os.path.basename(source_path)

    # 3. Context gathering (Scouted Context for target_cohort analysis)
    safe_top = "\n".join([c.text for c in chunks[:10]]) # Look deeper for scope/audience
    safe_bottom = "\n".join([c.text for c in chunks[-5:]]) if len(chunks) > 5 else ""
    
    scouted_middle = []
    valid_keywords = ["scope", "audience", "application"]
    for chunk in chunks[5:-15]: # Scan middle sections
        text_lower = chunk.text.lower().strip()
        headers = [h.lower() for h in getattr(chunk.meta, 'headings', [])] if hasattr(chunk.meta, 'headings') else []
        if any(keyword in h for h in headers for keyword in valid_keywords) or bool(re.match(r'^(section \d+ - )?(scope|audience|application)', text_lower)):
            scouted_middle.append(chunk.text)
            if len(scouted_middle) >= 3: break

    scouted_context = f"{safe_top}\n" + "\n".join(scouted_middle) + f"\n{safe_bottom}"

    # 4. Standard Date & Manager extraction (Remains the same)
    eff_match = re.search(r'Effective Date.*?(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}|\d{4}-\d{2}-\d{2})', scouted_context, re.IGNORECASE)
    rev_match = re.search(r'Review Date.*?(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}|\d{4}-\d{2}-\d{2})', scouted_context, re.IGNORECASE)
    mgr_match = re.search(r'Responsible Manager.*?\[(.*?)\]\s*\(mailto:(.*?)\)', scouted_context, re.IGNORECASE)
    
    final_enq_name = "University Administration"
    final_enq_email = ""
    enq_match_email = re.search(r'Enquiries Contact.*?=\s*\[(.*?)\]\s*\(mailto:(.*?)\)', scouted_context, re.IGNORECASE)
    if enq_match_email:
        final_enq_name, final_enq_email = enq_match_email.group(1).strip(), enq_match_email.group(2).strip()
    
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
            
            # THE FIX: Broadened the rejection to catch all "Section" headers
            if not candidate_lower.startswith("section") and not candidate_lower.startswith("part") and "status and details" not in candidate_lower:
                if not re.match(r'^[\(\d]', candidate):
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

        # --- NEW: ADVANCED TABLE EXTRACTION ---
        if is_real_table and hasattr(chunk.meta, "doc_items"):
            table_markdowns = []
            for item in chunk.meta.doc_items:
                if "table" in str(getattr(item, "label", "")).lower() and hasattr(item, "export_to_markdown"):
                    table_markdowns.append(item.export_to_markdown())
            
            # If we found markdown tables, overwrite the flat text!
            if table_markdowns:
                text = "\n\n".join(table_markdowns)
        # --------------------------------------

        chunk_is_exception = any(word in breadcrumb_lower for word in ["exclusion", "exemption", "exception", "waiver"]) or bool(strict_exception_pattern.search(text))
        chunk_specific_cohorts = set(global_cohorts)
        
        if any(word in breadcrumb_lower for word in ["staff", "admin", "employee"]): 
            chunk_specific_cohorts.update(["Academic", "Professional"])
            
        if any(word in breadcrumb_lower for word in ["student", "candidate", "learner"]): 
            # THE FIX: Only add student roles if they aren't explicitly banned by the title discards
            student_roles = {"Undergrad", "Postgrad", "HDR", "International"}
            title_lower = document_title.lower()
            
            # If the document is strictly HDR/Postgrad, do not add Undergrad back in
            if "Undergrad" not in global_cohorts and any(k in title_lower for k in ["graduate", "postgraduate", "hdr", "doctoral", "masters", "higher degree"]):
                student_roles.discard("Undergrad")
            
            chunk_specific_cohorts.update(student_roles)
            
        if "hdr" in breadcrumb_lower or "doctoral" in breadcrumb_lower: 
            chunk_specific_cohorts.update(["HDR", "Academic"])

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