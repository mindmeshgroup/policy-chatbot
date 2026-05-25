import hashlib
import json
import re
import os
import spacy
import numpy as np
import ollama
from datetime import datetime
from pydantic import BaseModel, ValidationError
from typing import List, Optional
from docling_core.transforms.chunker import HierarchicalChunker
from langchain_ollama import OllamaEmbeddings
from urllib.parse import urlparse, parse_qs

# ==========================================
# CONFIGURATION & HYPERPARAMETERS
# ==========================================
EXTRACTOR_MODEL = "llama3.2"
EMBEDDING_MODEL = "nomic-embed-text"

BUFFER_SIZE = 1                  # Step 2: Contextual sliding window size
BATCH_SIZE = 16                  # Step 3: Prevent Ollama memory timeouts
BREAKPOINT_PERCENTILE = 90       # Step 5: Dynamic percentile cut-off
VARIANCE_FLOOR = 0.05            # Step 5: Stop arbitrary cuts in uniform prose
MIN_CHUNK_SIZE = 400             # Step 6: Floor limit for low-context chunks
MAX_CHUNK_SIZE = 1500            # Step 6: Ceiling limit to prevent LLM window crashes

try:
    print("Loading spaCy NLP model for advanced sentence segmentation...")
    nlp = spacy.load("en_core_web_sm")
except OSError:
    print("[WARNING] spaCy model 'en_core_web_sm' not found. Run: python -m spacy download en_core_web_sm")
    nlp = None

embedder = OllamaEmbeddings(model=EMBEDDING_MODEL)

# ==========================================
# PYDANTIC DATA CONTRACT (SYSTEM BOUNDARY)
# ==========================================
class ContactDict(BaseModel):
    name: str
    email: str
    phone: Optional[str] = ""

class PolicyChunkPayload(BaseModel):
    # This config tells Pydantic to strictly respect this order
    model_config = {"populate_by_name": True, "extra": "allow"} 
    
    content: str
    has_table: bool
    is_exception: bool
    document_title: str
    source_url: str
    enquiries_contact: ContactDict
    responsible_manager: ContactDict
    escalation_contact: str
    breadcrumb: str
    document_summary: str      # Restored from your old code!
    doc_type: str
    category: str
    access_level: str
    target_cohort: List[str]
    campus_scope: List[str]
    document_id: str
    approval_body: str
    department_owner: ContactDict
    status: str = "Current"
    effective_date_iso: str
    review_date: str
    chunk_id: str
    chunk_index: int
    chunk_type: str
    chunking_method: str       # New auditing field kept neatly at the end


# ==========================================
# HELPER FUNCTIONS
# ==========================================
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
def get_document_title(chunks):
    """
    Looks through Docling hierarchy for the first reliable heading.
    Ignores injected metadata like SECTION 99.
    """
    for chunk in chunks:
        headers = getattr(chunk.meta, 'headings', [])
        if headers:
            candidate = headers[0].strip()
            # If it looks like a real policy title and not our injected meta
            if "SECTION 99" not in candidate.upper() and "STATUS" not in candidate.upper() and len(candidate) > 5:
                return candidate
    return None
# ==========================================
# CUSTOM 6-STEP SEMANTIC ENGINE
# ==========================================
def _custom_semantic_split(text: str) -> list:
    if len(text.strip()) <= MAX_CHUNK_SIZE:
        return [text]

    # --- STEP 1: SENTENCE SEGMENTATION & LIST MASKING ---
    safe_text = re.sub(r'\b(\d+)\.\s+', r'\1) ', text)
    safe_text = safe_text.replace("e.g.", "e.g").replace("i.e.", "i.e")

    if nlp:
        doc = nlp(safe_text)
        sentences = [sent.text.strip() for sent in doc.sents if sent.text.strip()]
    else:
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', safe_text) if s.strip()]

    if len(sentences) <= 1:
        return [text]

    # --- STEP 2: CREATING CONTEXTUAL BUFFERS ---
    sentence_buffers = []
    for i in range(len(sentences)):
        start = max(0, i - BUFFER_SIZE)
        end = min(len(sentences), i + BUFFER_SIZE + 1)
        sentence_buffers.append(" ".join(sentences[start:end]))

    # --- STEP 3: BATCHED EMBEDDING GENERATION ---
    vectors = []
    try:
        for i in range(0, len(sentence_buffers), BATCH_SIZE):
            batch = sentence_buffers[i:i+BATCH_SIZE]
            embeddings = embedder.embed_documents(batch)
            vectors.extend([np.array(emb) for emb in embeddings])
    except Exception as e:
        print(f"      [WARNING] Embedding calculation failed: {e}")
        return [text]

    # --- STEP 4: NORMALIZED COSINE DISTANCE ---
    distances = []
    for k in range(len(vectors) - 1):
        u, v = vectors[k], vectors[k+1]
        norm_u, norm_v = np.linalg.norm(u), np.linalg.norm(v)
        if norm_u == 0 or norm_v == 0:
            distances.append(0.0)
            continue
        
        similarity = np.clip(np.dot(u, v) / (norm_u * norm_v), -1.0, 1.0)
        distances.append(1.0 - similarity)

    if not distances:
        return [text]

    # --- STEP 5: VARIANCE GUARDRAIL & DYNAMIC THRESHOLDING ---
    if np.std(distances) < VARIANCE_FLOOR:
        return [text]

    threshold = np.percentile(distances, BREAKPOINT_PERCENTILE)
    breakpoints = [idx for idx, dist in enumerate(distances) if dist > threshold]

    # --- STEP 6: SLICING WITH 1-SENTENCE OVERLAP & CONSOLIDATION ---
    raw_semantic_chunks = []
    start_idx = 0
    
    for bp in breakpoints:
        end_idx = min(bp + 2, len(sentences)) 
        chunk_sents = sentences[start_idx : end_idx]
        raw_semantic_chunks.append(" ".join(chunk_sents))
        start_idx = max(0, bp) 

    if start_idx < len(sentences):
        raw_semantic_chunks.append(" ".join(sentences[start_idx:]))

    final_semantic_chunks = []
    working_buffer = ""

    for chunk in raw_semantic_chunks:
        if len(working_buffer) + len(chunk) < MIN_CHUNK_SIZE:
            working_buffer = f"{working_buffer}\n\n{chunk}".strip()
        elif len(working_buffer) + len(chunk) > MAX_CHUNK_SIZE:
            if working_buffer:
                final_semantic_chunks.append(working_buffer)
            if len(chunk) > MAX_CHUNK_SIZE:
                final_semantic_chunks.append(chunk[:MAX_CHUNK_SIZE])
                working_buffer = chunk[MAX_CHUNK_SIZE:]
            else:
                working_buffer = chunk
        else:
            working_buffer = f"{working_buffer}\n\n{chunk}".strip()
            final_semantic_chunks.append(working_buffer)
            working_buffer = ""

    if working_buffer:
        final_semantic_chunks.append(working_buffer)

    return final_semantic_chunks

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
            options={'temperature': 0.0, 'num_ctx': 4096}, 
            keep_alive="5m"
        )
        return json.loads(response['message']['content'])
    except Exception as e:
        print(f"      [!] Ollama Extraction Error: {e}")
        return {}

# ==========================================
# HYBRID WORKER 2: DETERMINISTIC FAILSAFE
# ==========================================
def _get_target_cohort(scouted_context, document_title, llm_roles=None):
    cohort_raw = llm_roles if llm_roles is not None else []
    if not isinstance(cohort_raw, list): cohort_raw = [cohort_raw]
    ALL_ROLES = ["Undergrad", "Postgrad", "HDR", "International", "Academic", "Professional", "Casual", "Alumni", "Public", "Guest"]
    
    final_set = {str(t).strip().title() for t in cohort_raw if str(t).strip().title() in ALL_ROLES}
    text_to_scan = (document_title + " " + scouted_context).lower()
    title_lower = document_title.lower()

    UNIVERSAL_KEYWORDS = ["all persons", "university community", "everyone", "individuals", "privacy", "safety", "conduct", "whistleblower", "compliance", "facilities", "integrity"]
    if any(re.search(rf"\b{term}\b", text_to_scan) for term in UNIVERSAL_KEYWORDS):
        final_set.update(ALL_ROLES)

    STUDENT_KEYWORDS = ["student", "learner", "candidate", "undergrad", "admission", "enrollment", "coursework", "exam", "assessment", "grade", "tuition", "scholarship"]
    if any(re.search(rf"\b{term}\b", text_to_scan) for term in STUDENT_KEYWORDS):
        final_set.update(["Undergrad", "Postgrad", "HDR", "International"])
        
    HDR_KEYWORDS = ["hdr", "doctoral", "phd", "research degree", "thesis", "graduate research"]
    if any(re.search(rf"\b{term}\b", text_to_scan) for term in HDR_KEYWORDS):
        final_set.update(["HDR", "Academic"])
        
    STAFF_KEYWORDS = ["staff", "employee", "workplace", "academic", "professional", "casual", "salary", "employment", "leave", "recruitment", "manager", "overtime"]
    if any(re.search(rf"\b{term}\b", text_to_scan) for term in STAFF_KEYWORDS):
        final_set.update(["Academic", "Professional", "Casual"])

    HR_TITLES = [
        "employment", "termination of employment", "remuneration", 
        "staff leave", "staff workload", "staff probation", 
        "performance review", "flexible working", "working from home", 
        "staff recruitment", "outside work", "conflict of interest" 
    ]
    if any(k in title_lower for k in HR_TITLES):
        final_set.difference_update(["Undergrad", "Postgrad", "HDR", "International", "Alumni", "Public", "Guest"])

    if any(k in title_lower for k in ["graduate", "postgraduate", "hdr", "doctoral", "masters", "higher degree", "research degree"]):
        final_set.difference_update(["Undergrad", "Alumni", "Public", "Guest"])
        
    if "undergraduate" in title_lower:
        final_set.difference_update(["Postgrad", "HDR"])

    if not final_set:
        return ALL_ROLES.copy()

    if any(role in final_set for role in ["Undergrad", "Postgrad", "HDR", "International"]): 
        final_set.add("Academic")

    return list(final_set)

def _consolidate_semantic_chunks(raw_chunks):
    """
    Merges adjacent chunks that share the same heading hierarchy, 
    provided they are not tables and the combined length remains safe.
    """
    if not raw_chunks: return []
    chunks = []
    current_chunk = raw_chunks[0]
    
    # Safety ceiling to prevent massive blocks from crashing the embedder
    SAFE_CONSOLIDATION_LIMIT = 2500 
    
    for nxt in raw_chunks[1:]:
        text_current = current_chunk.text.strip()
        text_next = nxt.text.strip()
        if not text_next: continue
            
        current_hierarchy = getattr(current_chunk.meta, 'headings', [])
        next_hierarchy = getattr(nxt.meta, 'headings', [])
        is_same_family = (current_hierarchy == next_hierarchy)
        
        is_real_table_current = any("table" in str(getattr(item, "label", "")).lower() for item in getattr(current_chunk.meta, "doc_items", []))
        is_real_table_next = any("table" in str(getattr(item, "label", "")).lower() for item in getattr(nxt.meta, "doc_items", []))
        
        combined_length = len(text_current) + len(text_next)
        
        # Merge only if it is safe to do so
        if is_same_family and not is_real_table_current and not is_real_table_next and combined_length < SAFE_CONSOLIDATION_LIMIT:
            current_chunk.text = f"{text_current}\n\n{text_next}"
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
# SPECIALIST EXTRACTORS
# ==========================================
def _extract_web_metadata(chunks, source_path):
    # document_title = "Unknown Policy"
    
    # # --- THE DOCLING HIERARCHY FIX ---
    # # We know CHUNK[0] is the injected SECTION 99 metadata.
    # # Therefore, the real document title is the root heading of the first non-Section-99 chunk.
    # for chunk in chunks:
    #     headers = getattr(chunk.meta, 'headings', [])
    #     if headers:
    #         candidate = headers[0].strip()
    #         candidate_upper = candidate.upper()
    #         if "SECTION 99" not in candidate_upper and "STATUS AND DETAILS" not in candidate_upper:
    #             document_title = candidate
    #             break # We found the authoritative title, stop searching

    # # Ultimate fallback just in case Docling completely failed to find headings
    # if document_title == "Unknown Policy":
    #     parsed_url = urlparse(source_path)
    #     query_params = parse_qs(parsed_url.query)
    #     if 'id' in query_params:
    #         document_title = f"Policy ID: {query_params['id'][0]}"
    #     else:
    #         document_title = os.path.basename(source_path).replace('-', ' ').title()

    safe_top = "\n".join([c.text for c in chunks[:10]])
    safe_bottom = "\n".join([c.text for c in chunks[-5:]]) if len(chunks) > 5 else ""
    
    scouted_middle = []
    valid_keywords = ["scope", "audience", "application"]
    for chunk in chunks[5:-15]:
        text_lower = chunk.text.lower().strip()
        headers = [h.lower() for h in getattr(chunk.meta, 'headings', [])] if hasattr(chunk.meta, 'headings') else []
        if any(keyword in h for h in headers for keyword in valid_keywords) or bool(re.match(r'^(section \d+ - )?(scope|audience|application)', text_lower)):
            scouted_middle.append(chunk.text)
            if len(scouted_middle) >= 3: break

    scouted_context = f"{safe_top}\n" + "\n".join(scouted_middle) + f"\n{safe_bottom}"

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
        "scouted_context": scouted_context,
        "iso_eff": standardize_date(eff_match.group(1)) if eff_match else "1970-01-01",
        "iso_rev": standardize_date(rev_match.group(1)) if rev_match else "2099-12-31",
        "manager_dict": {"name": mgr_match.group(1).strip(), "email": mgr_match.group(2).strip()} if mgr_match else {"name": "Executive Board", "email": ""},
        "enquiries_dict": {"name": final_enq_name, "email": final_enq_email, "phone": ""},
        "final_approval": appr_match.group(1).strip() if appr_match else "Academic Board",
        "final_status": status_match.group(1).strip() if status_match else "Current"
    }
def _extract_pdf_metadata(chunks, source_path):
    document_title = "Unknown Policy"
    
    for chunk in chunks[:10]:
        if hasattr(chunk.meta, 'headings') and chunk.meta.headings:
            candidate = chunk.meta.headings[0].strip()
            candidate_lower = candidate.lower()
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
def _split_markdown_table(table_text: str, max_chars: int = 1500) -> list[str]:
    """
    Splits a large Markdown table into smaller tables, ensuring every 
    sub-table retains the original header and separator rows.
    """
    lines = table_text.strip().split('\n')
    
    # A valid markdown table needs at least a header, separator, and one data row
    if len(lines) < 3:
        # Not a standard table, or too small to split safely. Fallback to raw text splitting if needed.
        return [table_text[:max_chars]] if len(table_text) > max_chars else [table_text]
        
    header_row = lines[0]
    separator_row = lines[1]
    
    # Quick sanity check that it actually looks like a markdown table
    if "|" not in header_row or "|-" not in separator_row.replace(" ", ""):
        # Not a markdown table. Truncate as a fallback to prevent crashes.
        return [table_text[:max_chars]] if len(table_text) > max_chars else [table_text]

    base_overhead = len(header_row) + len(separator_row) + 2 # +2 for newlines
    
    sub_tables = []
    current_table_lines = [header_row, separator_row]
    current_length = base_overhead
    
    for row in lines[2:]:
        row_length = len(row) + 1 # +1 for newline
        
        # If adding this row exceeds the limit, package the current table and start a new one
        if current_length + row_length > max_chars and len(current_table_lines) > 2:
            sub_tables.append("\n".join(current_table_lines))
            # Start a new table with the headers
            current_table_lines = [header_row, separator_row, row]
            current_length = base_overhead + row_length
        else:
            current_table_lines.append(row)
            current_length += row_length
            
    # Add the final table if it has data rows
    if len(current_table_lines) > 2:
        sub_tables.append("\n".join(current_table_lines))
        
    return sub_tables
# ==========================================
# PAYLOAD ASSEMBLY WITH METADATA-AS-TEXT (MaT)
# ==========================================
def _assemble_final_payload(chunks, source_path, metadata, global_cohorts, docling_document):
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

        # --- ADVANCED TABLE ELEMENT RECOVERY (MaT) ---
        if is_real_table and hasattr(chunk.meta, "doc_items"):
            table_markdowns = []
            for item in chunk.meta.doc_items:
                if "table" in str(getattr(item, "label", "")).lower() and hasattr(item, "export_to_markdown"):
                    table_markdowns.append(item.export_to_markdown(doc=docling_document))
            if table_markdowns:
                table_grid = "\n\n".join(table_markdowns)
                text = f"[Context: {document_title} | Table Segment under {breadcrumb}]\n{table_grid}"

        # Apply cohort exceptions and structural logic tagging
        chunk_is_exception = any(word in breadcrumb_lower for word in ["exclusion", "exemption", "exception", "waiver"]) or bool(strict_exception_pattern.search(text))
        chunk_specific_cohorts = set(global_cohorts)
        
        if any(word in breadcrumb_lower for word in ["staff", "admin", "employee"]): 
            chunk_specific_cohorts.update(["Academic", "Professional"])
            
        if any(word in breadcrumb_lower for word in ["student", "candidate", "learner"]): 
            student_roles = {"Undergrad", "Postgrad", "HDR", "International"}
            title_lower = document_title.lower()
            if "Undergrad" not in global_cohorts and any(k in title_lower for k in ["graduate", "postgraduate", "hdr", "doctoral", "masters", "higher degree"]):
                student_roles.discard("Undergrad")
            chunk_specific_cohorts.update(student_roles)
            
        if "hdr" in breadcrumb_lower or "doctoral" in breadcrumb_lower: 
            chunk_specific_cohorts.update(["HDR", "Academic"])

        # --- DUAL-LAYER RBAC INHERITANCE ---
        student_subroles = {"Undergrad", "Postgrad", "HDR", "International"}
        staff_subroles = {"Academic", "Professional", "Casual"}
        
        macro_extensions = set()
        for role in chunk_specific_cohorts:
            if role in student_subroles: macro_extensions.add("Student")
            if role in staff_subroles: macro_extensions.add("Staff")
            if role in ["Public", "Guest", "Alumni"]: macro_extensions.update(["Student", "Staff"])
            
        chunk_specific_cohorts.update(macro_extensions)

        # Blueprint base metadata dictionary
        # Blueprint base metadata dictionary
        base_dict = {
            "content": "", # placeholder, filled later
            "has_table": is_real_table, 
            "is_exception": chunk_is_exception, 
            "document_title": document_title,
            "source_url": source_path, 
            "enquiries_contact": metadata["enquiries_dict"],
            "responsible_manager": metadata["manager_dict"],
            "escalation_contact": "Ask La Trobe or Governance and Policy at policy@latrobe.edu.au.",
            "breadcrumb": breadcrumb,
            "document_summary": f"Policy regarding {document_title}.", # Make sure this is here!
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
            "chunk_index": i
        }
        temp_payloads = []

        # Ensure layout formatting context is measured accurately against MAX_CHUNK_SIZE
        content_to_send = f"[{breadcrumb}]\n{text}"

        # --- ROUTER: STRUCTURAL PASS-THROUGH VS LOSSLESS TABLE RETENTION VS SEMANTIC SPLITTING ---
        if len(text) <= MAX_CHUNK_SIZE:
            # Branch A: Chunk text or table fits completely within vector space boundaries
            payload = base_dict.copy()
            payload["content"] = content_to_send
            payload["chunk_id"] = hashlib.md5(f"{source_path}_chunk_{i}".encode('utf-8')).hexdigest()
            payload["chunk_type"] = "Table" if is_real_table else "Text"
            payload["chunking_method"] = "Atomic-Pass"
            temp_payloads.append(payload)
            
        elif is_real_table:
            # Branch B: Table overflows limits. Handle with header-retaining sub-table division
            sub_tables = _split_markdown_table(text, max_chars=MAX_CHUNK_SIZE)
            
            for j, sub_table_text in enumerate(sub_tables):
                payload = base_dict.copy()
                payload["content"] = f"[{breadcrumb}]\n{sub_table_text}"
                payload["chunk_id"] = hashlib.md5(f"{source_path}_chunk_{i}_subtable_{j}".encode('utf-8')).hexdigest()
                payload["chunk_type"] = "Table"
                payload["chunking_method"] = "Lossless-Table-Split"
                temp_payloads.append(payload)
                
        else:
            # Branch C: Standard text block exceeds limit. Execute target contextual sentence split
            sub_chunks = _custom_semantic_split(text)
            method_flag = "Semantic-Variance-Bypass" if len(sub_chunks) == 1 else "Hierarchical-Semantic-Optimized"
            
            for j, sub_text in enumerate(sub_chunks):
                payload = base_dict.copy()
                payload["content"] = f"[{breadcrumb}]\n{sub_text}"
                payload["chunk_id"] = hashlib.md5(f"{source_path}_chunk_{i}_sub_{j}".encode('utf-8')).hexdigest()
                payload["chunk_type"] = "Text"
                payload["chunking_method"] = method_flag
                temp_payloads.append(payload)

        # --- PYDANTIC SCHEMA VALIDATION LOOP ---
        for p_dict in temp_payloads:
            try:
                validated_model = PolicyChunkPayload(**p_dict)
                final_dict = validated_model.model_dump() if hasattr(validated_model, 'model_dump') else validated_model.dict()
                chunks_payload.append(final_dict)
            except ValidationError as e:
                print(f"      [CRITICAL] Pydantic Validation Failed for Chunk ID {p_dict.get('chunk_id')}: {e}")
                
    return chunks_payload

# ==========================================
# THE ORCHESTRATOR
# ==========================================
def extract_metadata_and_chunk(docling_document, source_path: str):
    chunker = HierarchicalChunker()
    raw_chunks = list(chunker.chunk(docling_document))
    if not raw_chunks: return []

    chunks = _consolidate_semantic_chunks(raw_chunks)
    scouted_context = "\n".join([c.text for c in chunks[:10]])


    document_title = get_document_title(chunks)

    # 2. Use LLM Guess if hierarchy fails
    if not document_title:
        filename_hint = os.path.basename(source_path).replace('-', ' ').title()
        llm_data = extract_llm_cohort(scouted_context, filename_hint)
        document_title = llm_data.get("document_title")

    # 3. Use the original URL/Filename Fallback (Your original safety net)
    if not document_title or "view.php" in document_title.lower() or document_title == "Unknown Policy":
        parsed_url = urlparse(source_path)
        query_params = parse_qs(parsed_url.query)
        document_title = f"Policy ID: {query_params['id'][0]}" if 'id' in query_params else os.path.basename(source_path).replace('-', ' ').title()

    # 4. Extract metadata (Web or PDF)
    is_pdf = source_path.lower().endswith('.pdf')
    if is_pdf:
        # PDF helper remains 100% untouched
        metadata = _extract_pdf_metadata(chunks, source_path)
    else:
        # Pass the title into the web metadata helper so it doesn't need to guess
        metadata = _extract_web_metadata(chunks, source_path)

    # 5. Overwrite the result with our verified title
    metadata["document_title"] = document_title

    # 6. Assembly
    llm_target_cohort = extract_llm_cohort(scouted_context, document_title).get("target_cohort", [])
    global_cohorts = _get_target_cohort(metadata["scouted_context"], document_title, llm_target_cohort)
    
    return _assemble_final_payload(chunks, source_path, metadata, global_cohorts, docling_document)