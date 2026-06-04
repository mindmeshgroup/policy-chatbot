import json
import re
import hashlib
from pathlib import Path

from retrieval.utils.schemas import PolicyChunkPayload
from pydantic import ValidationError

from retrieval.utils.ai_client import extract_llm_cohort
from retrieval.utils.taxonomy_rules import (
    _contains_term,
    _get_base_primary_cohorts,
    _get_base_contextual_tags,
    STUDENT_TERMS,
    STAFF_TERMS,
    PUBLIC_PHRASES,
    UNIVERSAL_PHRASES
)

# Save validated chunk payloads separately before they are inserted into Qdrant.
VALIDATED_DIR = Path(__file__).resolve().parents[2] / "data" / "3_validated"
VALIDATED_DIR.mkdir(parents=True, exist_ok=True)

def _get_section_path(breadcrumb: str, document_title: str) -> str:
    """
    Removes the document title from the breadcrumb so that section-level
    audience tagging is based on the heading of the current chunk only.
    """
    breadcrumb_clean = breadcrumb.strip()
    title_clean = document_title.strip()

    if breadcrumb_clean.casefold() == title_clean.casefold():
        return ""

    prefix = f"{title_clean} > "
    if breadcrumb_clean.casefold().startswith(prefix.casefold()):
        return breadcrumb_clean[len(prefix):].casefold()

    return breadcrumb_clean.casefold()

def generate_canonical_document_id(document_title: str) -> str:
    """
    Creates a stable identifier used to group equivalent versions of one policy.
    """
    normalised_title = re.sub(
        r"[^a-z0-9]+",
        "",
        document_title.casefold(),
    )

    if not normalised_title:
        raise ValueError("Cannot generate canonical document ID from an empty title.")

    return hashlib.sha256(
        normalised_title.encode("utf-8")
    ).hexdigest()[:12]

# -------------------------------------------------------------------------
# Chunk payload construction
# -------------------------------------------------------------------------
def process_single_chunk(
    chunk,
    metadata,
    document_title,
    source_url,
    document_id,
    canonical_document_id,
    i,
    base_primary_cohorts,
    base_contextual_tags,
    strict_exception_pattern,
    is_vehicle_driver_policy,
    has_student_driver_audience,
    has_external_driver_audience,
):
    """Builds the metadata payload for one policy chunk before validation."""
    text = chunk["content"]
    breadcrumb = chunk["breadcrumb"]
    is_table = chunk["is_table"]

    department_owner = (
        metadata.get("department_owner")
        or metadata.get("enquiries_contact")
        or {}
    )
    # Remove website footer text before storing the retrieval chunk.
    text = re.sub(
        r"\s*© Copyright \d{4} La Trobe University\..*$",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    ).strip()

    # Remove a trailing CRICOS footer while preserving policy content earlier in the chunk.
    text = re.sub(
        r"\s*All rights reserved\.\s*CRICOS Provider Code:.*$",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    ).strip()

    # Remove repeated webpage navigation links before storing retrieval content.
    text = re.sub(
        r"\s*\[Top of Page\]\(#document-top\)\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()

    # Use only the section path for chunk-level audience decisions.
    section_path_lower = _get_section_path(breadcrumb, document_title)
    chunk_text_to_scan = f"{section_path_lower} {text}".casefold()
    
    # Flag chunks that contain wording about exceptions or excluded cases.
    chunk_is_exception = bool(strict_exception_pattern.search(text))
    
    # Retain detailed audience predictions for future expert validation.
    contextual_audience_tags = set(base_contextual_tags)
    if _contains_term(section_path_lower, ["undergraduate", "undergrad"]):
        contextual_audience_tags.add("Undergrad")
    if _contains_term(section_path_lower, ["postgraduate", "masters", "master's"]):
        contextual_audience_tags.add("Postgrad")
    if _contains_term(section_path_lower, ["hdr", "doctoral", "phd"]):
        contextual_audience_tags.add("HDR")
    if _contains_term(section_path_lower, ["international student", "overseas student"]):
        contextual_audience_tags.add("International")
    if _contains_term(section_path_lower, ["academic staff", "lecturer"]):
        contextual_audience_tags.add("Academic")
    if _contains_term(section_path_lower, ["professional staff", "administrative staff"]):
        contextual_audience_tags.add("Professional")
    if _contains_term(section_path_lower, ["casual staff", "sessional staff"]):
        contextual_audience_tags.add("Casual")

    text_lower = text.casefold()
    if _contains_term(text_lower, ["official visitors", "contractors"]):
        contextual_audience_tags.add("Guest")

    # Use headings to refine chunk audience and body text to add relevant context.
    heading_cohorts = set()
    body_additions = set()

    driver_rule_sections = [
        "authorised drivers",
        "driver obligations",
        "traffic offences",
        "no smoking",
        "driver training",
        "accidents",
        "vehicle refuelling",
        "vehicle use log",
        "telematics",
        "parking",
        "car share",
        "definitions",
    ]

    if any(phrase in chunk_text_to_scan for phrase in UNIVERSAL_PHRASES):
        primary_cohorts = {"Student", "Staff", "Public"}
    else:
        if _contains_term(section_path_lower, STUDENT_TERMS):
            heading_cohorts.add("Student")
        if _contains_term(section_path_lower, STAFF_TERMS):
            heading_cohorts.add("Staff")
        if any(phrase in section_path_lower for phrase in PUBLIC_PHRASES):
            heading_cohorts.add("Public")

        if heading_cohorts:
            primary_cohorts = heading_cohorts
        else:
            primary_cohorts = set(base_primary_cohorts)

            if _contains_term(text_lower, STUDENT_TERMS):
                body_additions.add("Student")
            if _contains_term(text_lower, STAFF_TERMS):
                body_additions.add("Staff")
            if any(phrase in text_lower for phrase in PUBLIC_PHRASES):
                body_additions.add("Public")

            primary_cohorts.update(body_additions)

    # Extend shared driver rules only where this vehicle policy identifies additional authorised drivers.
    if (
        is_vehicle_driver_policy
        and any(term in section_path_lower for term in driver_rule_sections)
    ):
        primary_cohorts.add("Staff")

        if has_student_driver_audience:
            primary_cohorts.add("Student")

        if has_external_driver_audience:
            primary_cohorts.add("Public")

    # Use Public only when no student or staff audience can be identified.
    if not primary_cohorts:
        primary_cohorts.add("Public")

    # Return the raw payload with the injected canonical ID. The Pydantic model validates it in the main workflow.
    return {
        "content": text, "has_table": is_table, "is_exception": chunk_is_exception,
        "document_title": document_title, "source_url": source_url,
        "enquiries_contact": metadata.get("enquiries_contact", {}),
        "responsible_manager": metadata.get("responsible_manager", {}),
        "escalation_contact": "Ask La Trobe or Governance and Policy at policy@latrobe.edu.au.",
        "breadcrumb": breadcrumb, "document_summary": document_title, 
        "doc_type": "Procedure" if "procedure" in document_title.casefold() else "Policy", 
        "category": "La Trobe Policy Library", "access_level": "Public", 
        "target_cohort": sorted(list(primary_cohorts)),
        "contextual_audience_tags": sorted(list(contextual_audience_tags)),
        "campus_scope": ["All Campuses"], 
        "document_id": document_id,
        "canonical_document_id": canonical_document_id,
        "approval_body": metadata.get("approval_body"),
        "department_owner": department_owner,
        "status": metadata.get("status"), "effective_date_iso": metadata.get("effective_date_iso"),
        "review_date": metadata.get("review_date"),
        "chunk_id": hashlib.sha256(f"{document_id}_chunk_{i}".encode("utf-8")).hexdigest()[:24],
        "chunk_index": i, "chunk_type": "Table" if is_table else "Text",
        "chunking_method": chunk.get("chunking_method", "Unknown")
    }

# -------------------------------------------------------------------------
# Validated document output workflow
# -------------------------------------------------------------------------
def validate_and_tag_document(file_path: str) -> str:
    """
    Creates audience metadata for one chunked policy document, validates each
    chunk payload and saves the validated output for database insertion.
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    metadata = data["metadata"]
    chunks = data["chunks"]
    document_title = metadata["document_title"]
    source_url = metadata["source_url"]
    
    print(f"   [AI Validation] Tagging cohorts and verifying contracts for: {document_title}...")

    # Use the first substantive chunks for document-level audience extraction.
    # Navigation and footer text is excluded so it cannot broaden document tags.
    scouted_chunks = []

    for chunk in chunks:
        candidate_text = chunk["content"]
        candidate_lower = candidate_text.casefold()

        if "hide navigation" in candidate_lower:
            continue

        if "cricos provider code" in candidate_lower:
            continue

        candidate_text = re.sub(
            r"\s*\[Top of Page\]\(#document-top\)\s*",
            "",
            candidate_text,
            flags=re.IGNORECASE,
        ).strip()

        if candidate_text:
            scouted_chunks.append(candidate_text)

        if len(scouted_chunks) == 5:
            break

    scouted_context = "\n".join(scouted_chunks)

    if not scouted_context:
        raise RuntimeError(
            f"No substantive chunk content was available for '{document_title}'."
        )

    llm_response = extract_llm_cohort(scouted_context, document_title)
    
    # Keep the parser-derived title for storage and report any LLM title mismatch.
    llm_title = llm_response.get("document_title", "").strip()
    if llm_title and llm_title.casefold() != document_title.casefold():
        print(f"   [WARNING] Extracted title differs from staged title: '{llm_title}' != '{document_title}'")
    
    # Broad cohort tags are used by the current retrieval filter.
    base_primary_cohorts = _get_base_primary_cohorts(scouted_context, document_title)

    # Detailed LLM predictions are retained separately for future evaluation.
    base_contextual_tags = _get_base_contextual_tags(
        scouted_context,
        document_title,
        llm_response.get("target_cohort", []),
    )
    
    # Use the source URL to create one stable identifier for all chunks in the policy.
    document_id = hashlib.sha256(source_url.encode('utf-8')).hexdigest()[:12]

    # Calculate the canonical ID ONCE per document.
    canonical_document_id = generate_canonical_document_id(document_title)

    # Identify chunks that contain exception, waiver or exclusion wording.
    strict_exception_pattern = re.compile(
        r"\b("
        r"unless|"
        r"except where|"
        r"exceptions?|"
        r"notwithstanding|"
        r"exempt(?:ed)? from|"
        r"does not apply to|"
        r"waivers?|"
        r"exclusions?"
        r")\b",
        re.IGNORECASE,
    )

    # Scan the full policy only for cross-section rules that cannot be found
    # reliably from the first few chunks alone.
    full_document_context = "\n".join(chunk["content"] for chunk in chunks).casefold()

    # Apply shared-driver audience rules only to policies about university vehicles.
    is_vehicle_driver_policy = (
        "vehicle" in document_title.casefold()
        or "university fleet vehicle" in full_document_context
        or "university business travel" in full_document_context
    )

    # Identify whether this policy permits students or external users to drive.
    has_student_driver_audience = (
        "students of la trobe university" in full_document_context
        or "student drivers" in full_document_context
    )

    has_external_driver_audience = (
        "official visitors" in full_document_context
        or "contractors" in full_document_context
    )

    validated_payloads = []
    validation_errors = []

    # Build and validate each chunk before saving the completed document output.
    for i, chunk in enumerate(chunks):
        
        # Skip navigation-only chunks that would add retrieval noise.
        chunk_content_lower = chunk["content"].casefold()
        if "hide navigation" in chunk_content_lower:
            continue

        raw_payload = process_single_chunk(
            chunk, metadata, document_title, source_url, document_id, canonical_document_id, i, 
            base_primary_cohorts, base_contextual_tags, strict_exception_pattern, 
            is_vehicle_driver_policy, has_student_driver_audience, has_external_driver_audience
        )

        # Check if regex cleaning deleted all the text (leaving only the bracketed breadcrumb)
        content_without_breadcrumb = re.sub(
            r"^\[[^\]]+\]\s*",
            "",
            raw_payload["content"],
        ).strip()

        # If there is no actual body text left, skip this chunk completely.
        if not content_without_breadcrumb:
            continue

        try:
            validated_model = PolicyChunkPayload(**raw_payload)
            validated_payloads.append(validated_model.model_dump())
        except ValidationError as exc:
            validation_errors.append(f"Chunk {i}: {exc}")

    # Do not save a partial document if any chunk fails validation.
    if validation_errors:
        raise RuntimeError(f"Validation failed for {len(validation_errors)} chunk(s) in '{document_title}'.\n" + "\n".join(validation_errors))

    # Save only chunk payloads that have passed validation.
    output_data = {"metadata": metadata, "chunks": validated_payloads}
    out_path = VALIDATED_DIR / Path(file_path).name
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=4)
        
    return str(out_path)