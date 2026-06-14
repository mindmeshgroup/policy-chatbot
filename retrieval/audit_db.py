import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient

try:
    from retrieval.config import (
        COLLECTION_ALIAS,
        DENSE_VECTOR_NAME,
        QDRANT_API_KEY,
        QDRANT_URL,
        SPARSE_VECTOR_NAME,
    )
except ImportError:
    # Safe defaults for running the audit as a standalone script.
    COLLECTION_ALIAS = "university_policies"
    DENSE_VECTOR_NAME = "text-dense"
    SPARSE_VECTOR_NAME = "text-sparse"
    QDRANT_URL = "http://localhost:6333"
    QDRANT_API_KEY = None


# -------------------------------------------------------------------------
# Audit configuration
# -------------------------------------------------------------------------

# These expected values describe the promoted 20-policy evidence collection.
# They may be overridden later when auditing a full-library build.
EXPECTED_DOCUMENT_COUNT = int(os.getenv("EXPECTED_DOCUMENT_COUNT", "20"))
EXPECTED_CHUNK_COUNT = int(os.getenv("EXPECTED_CHUNK_COUNT", "684"))

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "audit_outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

REPORT_PATH = OUTPUT_DIR / "database_audit_report.json"
TITLES_PATH = OUTPUT_DIR / "database_titles.json"
DOCUMENT_SUMMARY_PATH = OUTPUT_DIR / "per_document_audit_summary.json"

PRIMARY_COHORTS = {"Student", "Staff", "Public"}
CONTEXTUAL_AUDIENCE_TAGS = {
    "Undergrad",
    "Postgrad",
    "HDR",
    "International",
    "Academic",
    "Professional",
    "Casual",
    "Alumni",
    "Guest",
}

REQUIRED_PAYLOAD_FIELDS = {
    "content",
    "has_table",
    "is_exception",
    "document_title",
    "source_url",
    "enquiries_contact",
    "responsible_manager",
    "escalation_contact",
    "breadcrumb",
    "document_summary",
    "doc_type",
    "category",
    "access_level",
    "target_cohort",
    "contextual_audience_tags",
    "campus_scope",
    "document_id",
    "canonical_document_id",
    "approval_body",
    "department_owner",
    "status",
    "effective_date_iso",
    "review_date",
    "chunk_id",
    "chunk_index",
    "chunk_type",
    "chunking_method",
}

REQUIRED_PAYLOAD_INDEXES = {
    "canonical_document_id",
    "target_cohort",
    "is_exception",
    "access_level",
}


# -------------------------------------------------------------------------
# Formatting and serialisation helpers
# -------------------------------------------------------------------------

def normalise_contact(contact: Any) -> dict[str, Any]:
    """Returns the contact object in a stable comparable form."""
    if not isinstance(contact, dict):
        return {"name": None, "email": None, "phone": None}

    return {
        "name": contact.get("name"),
        "email": contact.get("email"),
        "phone": contact.get("phone"),
    }


def object_to_dict(value: Any) -> Any:
    """Converts Qdrant response models into JSON-compatible values where possible."""
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return value


def print_check(label: str, passed: bool, detail: str) -> None:
    """Prints one readable PASS/WARN audit line."""
    status = "PASS" if passed else "WARN"
    print(f"[{status}] {label}: {detail}")


def resolve_alias_target(client: QdrantClient, alias_name: str) -> str:
    """Finds the physical collection currently published through the live alias."""
    try:
        aliases = client.get_aliases().aliases

        for alias in aliases:
            if alias.alias_name == alias_name:
                return alias.collection_name
    except Exception as exc:
        print(f"[WARN] Could not resolve alias metadata directly: {exc}")

    # Collection operations can still use the alias even when the backing
    # physical name could not be read.
    return alias_name


def scroll_all_payloads(client: QdrantClient, collection_name: str) -> list[dict]:
    """Loads payloads from every stored chunk in the active alias-backed collection."""
    payloads: list[dict] = []
    offset = None

    while True:
        records, next_offset = client.scroll(
            collection_name=collection_name,
            limit=200,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )

        for record in records:
            payloads.append(record.payload or {})

        if next_offset is None:
            break

        offset = next_offset

    return payloads


# -------------------------------------------------------------------------
# Database audit
# -------------------------------------------------------------------------

def audit_database() -> None:
    """
    Audits the currently published Qdrant collection against the implemented
    metadata and retrieval design.
    """
    client = QdrantClient(
        url=QDRANT_URL,
        api_key=QDRANT_API_KEY,
    )

    print("=" * 76)
    print("LA TROBE POLICY DATABASE - FINAL PAYLOAD AND PUBLICATION AUDIT")
    print("=" * 76)

    active_collection = resolve_alias_target(client, COLLECTION_ALIAS)
    print(f"Live alias             : {COLLECTION_ALIAS}")
    print(f"Published collection   : {active_collection}")

    try:
        collection_info = client.get_collection(active_collection)
    except Exception:
        collection_info = client.get_collection(COLLECTION_ALIAS)

    payloads = scroll_all_payloads(client, COLLECTION_ALIAS)

    titles = sorted({
        str(payload.get("document_title", "")).strip()
        for payload in payloads
        if str(payload.get("document_title", "")).strip()
    })

    title_chunk_counts = Counter(
        payload.get("document_title", "[Missing title]")
        for payload in payloads
    )

    print("\n1. COLLECTION PUBLICATION AND SCALE")
    print("-" * 76)

    print_check(
        "Published alias is accessible",
        bool(payloads),
        f"{len(payloads)} stored chunk payload(s) were read through '{COLLECTION_ALIAS}'.",
    )
    print_check(
        "Expected policy count",
        len(titles) == EXPECTED_DOCUMENT_COUNT,
        f"Found {len(titles)} unique policy title(s); expected {EXPECTED_DOCUMENT_COUNT}.",
    )
    print_check(
        "Expected chunk count",
        len(payloads) == EXPECTED_CHUNK_COUNT,
        f"Found {len(payloads)} chunk(s); expected {EXPECTED_CHUNK_COUNT}.",
    )

    print("\nStored policy titles:")
    for title in titles:
        print(f" - {title} ({title_chunk_counts[title]} chunks)")

    # ---------------------------------------------------------------------
    # Payload contract validation
    # ---------------------------------------------------------------------

    missing_field_counts: Counter[str] = Counter()
    empty_content_chunks: list[str] = []
    missing_chunk_ids: list[str] = []

    for payload in payloads:
        for field in REQUIRED_PAYLOAD_FIELDS:
            if field not in payload:
                missing_field_counts[field] += 1

        chunk_id = str(payload.get("chunk_id", "")).strip()

        if not str(payload.get("content", "")).strip():
            empty_content_chunks.append(chunk_id or "[Missing chunk ID]")

        if not chunk_id:
            missing_chunk_ids.append(
                str(payload.get("document_title", "[Missing title]"))
            )

    print("\n2. PAYLOAD CONTRACT AND CONTENT COMPLETENESS")
    print("-" * 76)

    print_check(
        "Required payload fields",
        not missing_field_counts,
        (
            "All required payload fields are present."
            if not missing_field_counts
            else f"Missing field counts: {dict(missing_field_counts)}"
        ),
    )
    print_check(
        "Chunk content is populated",
        not empty_content_chunks,
        (
            "No empty content fields detected."
            if not empty_content_chunks
            else f"{len(empty_content_chunks)} empty content field(s) detected."
        ),
    )
    print_check(
        "Chunk identifiers are populated",
        not missing_chunk_ids,
        (
            "All chunks contain chunk_id values."
            if not missing_chunk_ids
            else f"{len(missing_chunk_ids)} chunk(s) have no chunk_id."
        ),
    )

    # ---------------------------------------------------------------------
    # Role and contextual metadata segregation
    # ---------------------------------------------------------------------

    invalid_primary_tags: list[dict] = []
    empty_primary_tags: list[str] = []
    invalid_contextual_tags: list[dict] = []
    primary_tag_counts: Counter[str] = Counter()
    contextual_tag_counts: Counter[str] = Counter()

    for payload in payloads:
        title = payload.get("document_title", "[Missing title]")
        chunk_id = payload.get("chunk_id", "[Missing chunk ID]")
        primary_tags = payload.get("target_cohort", [])
        contextual_tags = payload.get("contextual_audience_tags", [])

        if not isinstance(primary_tags, list) or not primary_tags:
            empty_primary_tags.append(str(chunk_id))
            primary_tags = []

        invalid_primary = set(primary_tags) - PRIMARY_COHORTS
        if invalid_primary:
            invalid_primary_tags.append({
                "chunk_id": chunk_id,
                "document_title": title,
                "invalid_tags": sorted(invalid_primary),
            })

        if not isinstance(contextual_tags, list):
            contextual_tags = ["[Invalid non-list value]"]

        invalid_contextual = set(contextual_tags) - CONTEXTUAL_AUDIENCE_TAGS
        if invalid_contextual:
            invalid_contextual_tags.append({
                "chunk_id": chunk_id,
                "document_title": title,
                "invalid_tags": sorted(invalid_contextual),
            })

        primary_tag_counts.update(primary_tags)
        contextual_tag_counts.update(contextual_tags)

    print("\n3. ROLE-AWARE METADATA SEGREGATION")
    print("-" * 76)

    print_check(
        "Primary retrieval cohorts",
        not invalid_primary_tags and not empty_primary_tags,
        (
            f"Only broad roles stored in target_cohort: {dict(primary_tag_counts)}."
            if not invalid_primary_tags and not empty_primary_tags
            else (
                f"{len(invalid_primary_tags)} invalid primary-tag chunk(s); "
                f"{len(empty_primary_tags)} empty primary-tag chunk(s)."
            )
        ),
    )
    print_check(
        "Contextual audience taxonomy",
        not invalid_contextual_tags,
        (
            f"Contextual tag counts: {dict(contextual_tag_counts)}."
            if not invalid_contextual_tags
            else f"{len(invalid_contextual_tags)} invalid contextual-tag chunk(s)."
        ),
    )

    # ---------------------------------------------------------------------
    # IDs, version grouping and duplicate detection
    # ---------------------------------------------------------------------

    chunks_by_id: Counter[str] = Counter(
        str(payload.get("chunk_id"))
        for payload in payloads
        if payload.get("chunk_id")
    )
    duplicate_chunk_ids = {
        chunk_id: count
        for chunk_id, count in chunks_by_id.items()
        if count > 1
    }

    canonical_ids_by_title: defaultdict[str, set[str]] = defaultdict(set)

    for payload in payloads:
        title = str(payload.get("document_title", "[Missing title]"))
        canonical_id = str(payload.get("canonical_document_id", "")).strip()

        if canonical_id:
            canonical_ids_by_title[title].add(canonical_id)

    missing_canonical_titles = sorted(
        title
        for title in titles
        if not canonical_ids_by_title.get(title)
    )
    titles_with_multiple_canonical_ids = {
        title: sorted(ids)
        for title, ids in canonical_ids_by_title.items()
        if len(ids) > 1
    }

    print("\n4. DOCUMENT VERSION AND CHUNK IDENTIFIER CONSISTENCY")
    print("-" * 76)

    print_check(
        "Duplicate chunk IDs",
        not duplicate_chunk_ids,
        (
            "No duplicate chunk_id values detected."
            if not duplicate_chunk_ids
            else f"Duplicate IDs detected: {duplicate_chunk_ids}"
        ),
    )
    print_check(
        "Canonical document IDs",
        not missing_canonical_titles and not titles_with_multiple_canonical_ids,
        (
            "Each stored policy title maps to one canonical_document_id."
            if not missing_canonical_titles and not titles_with_multiple_canonical_ids
            else (
                f"Missing canonical IDs for: {missing_canonical_titles}; "
                f"multiple IDs: {titles_with_multiple_canonical_ids}"
            )
        ),
    )

    # ---------------------------------------------------------------------
    # Source URL and contact ownership checks
    # ---------------------------------------------------------------------

    pdf_source_chunks: list[str] = []
    non_public_source_chunks: list[str] = []
    contact_mismatches: list[dict] = []

    for payload in payloads:
        chunk_id = payload.get("chunk_id", "[Missing chunk ID]")
        source_url = str(payload.get("source_url", "")).strip()
        enquiries = normalise_contact(payload.get("enquiries_contact"))
        owner = normalise_contact(payload.get("department_owner"))

        if source_url.casefold().endswith(".pdf"):
            pdf_source_chunks.append(str(chunk_id))

        if "policies.latrobe.edu.au/document/view.php" not in source_url:
            non_public_source_chunks.append(str(chunk_id))

        if enquiries != owner:
            contact_mismatches.append({
                "chunk_id": chunk_id,
                "document_title": payload.get("document_title"),
                "enquiries_contact": enquiries,
                "department_owner": owner,
            })

    print("\n5. SOURCE DOMINANCE AND CONTACT MAPPING")
    print("-" * 76)

    print_check(
        "HTML policy source dominance",
        not pdf_source_chunks and not non_public_source_chunks,
        (
            "All stored chunks reference public HTML policy-view sources."
            if not pdf_source_chunks and not non_public_source_chunks
            else (
                f"{len(pdf_source_chunks)} PDF-source chunk(s); "
                f"{len(non_public_source_chunks)} unexpected source URL chunk(s)."
            )
        ),
    )
    print_check(
        "Department owner mapping",
        not contact_mismatches,
        (
            "department_owner matches enquiries_contact for all chunks."
            if not contact_mismatches
            else f"{len(contact_mismatches)} contact mapping mismatch(es) detected."
        ),
    )

    # ---------------------------------------------------------------------
    # Boolean field and chunking-method evidence
    # ---------------------------------------------------------------------

    invalid_boolean_fields: list[dict] = []
    exception_count = 0
    table_count = 0
    chunking_method_counts: Counter[str] = Counter()

    for payload in payloads:
        chunk_id = payload.get("chunk_id", "[Missing chunk ID]")

        for field in ("has_table", "is_exception"):
            if not isinstance(payload.get(field), bool):
                invalid_boolean_fields.append({
                    "chunk_id": chunk_id,
                    "field": field,
                    "value": payload.get(field),
                })

        if payload.get("is_exception") is True:
            exception_count += 1

        if payload.get("has_table") is True:
            table_count += 1

        chunking_method_counts.update([
            str(payload.get("chunking_method", "[Missing method]"))
        ])

    print("\n6. STRUCTURED CONTENT FLAGS AND CHUNKING EVIDENCE")
    print("-" * 76)

    print_check(
        "Boolean content flags",
        not invalid_boolean_fields,
        (
            f"is_exception=True for {exception_count} chunk(s); "
            f"has_table=True for {table_count} chunk(s)."
            if not invalid_boolean_fields
            else f"{len(invalid_boolean_fields)} invalid boolean field value(s)."
        ),
    )
    print("Chunking method counts:")
    for method, count in sorted(chunking_method_counts.items()):
        print(f" - {method}: {count}")

    # ---------------------------------------------------------------------
    # Collection configuration: indexes and named vectors
    # ---------------------------------------------------------------------

    collection_info_dict = object_to_dict(collection_info)
    if not isinstance(collection_info_dict, dict):
        collection_info_dict = {}

    payload_schema = collection_info_dict.get("payload_schema", {}) or {}
    indexed_fields = set(payload_schema.keys())
    missing_indexes = sorted(REQUIRED_PAYLOAD_INDEXES - indexed_fields)

    config = collection_info_dict.get("config", {}) or {}
    params = config.get("params", {}) or {}
    vectors_config = params.get("vectors", {}) or {}
    sparse_vectors_config = params.get("sparse_vectors", {}) or {}
    quantization_config = config.get("quantization_config")

    dense_vector_configured = (
        isinstance(vectors_config, dict)
        and DENSE_VECTOR_NAME in vectors_config
    )
    sparse_vector_configured = (
        isinstance(sparse_vectors_config, dict)
        and SPARSE_VECTOR_NAME in sparse_vectors_config
    )

    print("\n7. HYBRID SEARCH CONFIGURATION AND FILTER INDEXES")
    print("-" * 76)

    print_check(
        "Dense named vector",
        dense_vector_configured,
        f"Expected named vector: {DENSE_VECTOR_NAME}.",
    )
    print_check(
        "Sparse named vector",
        sparse_vector_configured,
        f"Expected named vector: {SPARSE_VECTOR_NAME}.",
    )
    print_check(
        "Required payload indexes",
        not missing_indexes,
        (
            f"Indexed fields confirmed: {sorted(REQUIRED_PAYLOAD_INDEXES)}."
            if not missing_indexes
            else f"Missing payload index(es): {missing_indexes}."
        ),
    )
    print_check(
        "Scalar quantisation",
        quantization_config is not None,
        (
            "Quantisation configuration detected."
            if quantization_config is not None
            else "No quantisation configuration reported by Qdrant."
        ),
    )

    # ---------------------------------------------------------------------
    # Per-document summary and evidence file outputs
    # ---------------------------------------------------------------------

    document_summaries: list[dict] = []

    for title in titles:
        document_payloads = [
            payload
            for payload in payloads
            if payload.get("document_title") == title
        ]

        document_primary_tags = sorted({
            tag
            for payload in document_payloads
            for tag in payload.get("target_cohort", [])
        })
        document_contextual_tags = sorted({
            tag
            for payload in document_payloads
            for tag in payload.get("contextual_audience_tags", [])
        })
        document_canonical_ids = sorted({
            str(payload.get("canonical_document_id", "")).strip()
            for payload in document_payloads
            if str(payload.get("canonical_document_id", "")).strip()
        })
        document_source_urls = sorted({
            str(payload.get("source_url", "")).strip()
            for payload in document_payloads
            if str(payload.get("source_url", "")).strip()
        })
        document_chunking_methods = Counter(
            str(payload.get("chunking_method", "[Missing method]"))
            for payload in document_payloads
        )

        document_summaries.append({
            "document_title": title,
            "chunk_count": len(document_payloads),
            "canonical_document_ids": document_canonical_ids,
            "source_urls": document_source_urls,
            "target_cohorts": document_primary_tags,
            "contextual_audience_tags": document_contextual_tags,
            "exception_chunk_count": sum(
                1 for payload in document_payloads
                if payload.get("is_exception") is True
            ),
            "table_chunk_count": sum(
                1 for payload in document_payloads
                if payload.get("has_table") is True
            ),
            "chunking_method_counts": dict(
                sorted(document_chunking_methods.items())
            ),
        })

    print("\n8. PER-DOCUMENT DATABASE COVERAGE SUMMARY")
    print("-" * 76)

    for document in document_summaries:
        print(f"Document: {document['document_title']}")
        print(f"  Chunks:              {document['chunk_count']}")
        print(f"  Canonical ID(s):     {document['canonical_document_ids']}")
        print(f"  Target cohorts:      {document['target_cohorts']}")
        print(f"  Contextual tags:     {document['contextual_audience_tags']}")
        print(f"  Exception chunks:    {document['exception_chunk_count']}")
        print(f"  Table chunks:        {document['table_chunk_count']}")
        print(f"  Chunking methods:    {document['chunking_method_counts']}")
        print(f"  Source URL(s):       {document['source_urls']}")
        print()

    with open(TITLES_PATH, "w", encoding="utf-8") as titles_file:
        json.dump(titles, titles_file, indent=2)

    with open(DOCUMENT_SUMMARY_PATH, "w", encoding="utf-8") as summary_file:
        json.dump(document_summaries, summary_file, indent=2)

    warnings = {
        "missing_field_counts": dict(missing_field_counts),
        "empty_content_chunk_ids": empty_content_chunks,
        "missing_chunk_ids": missing_chunk_ids,
        "invalid_primary_tags": invalid_primary_tags,
        "empty_primary_tag_chunk_ids": empty_primary_tags,
        "invalid_contextual_tags": invalid_contextual_tags,
        "duplicate_chunk_ids": duplicate_chunk_ids,
        "missing_canonical_titles": missing_canonical_titles,
        "titles_with_multiple_canonical_ids": titles_with_multiple_canonical_ids,
        "pdf_source_chunk_ids": pdf_source_chunks,
        "unexpected_source_chunk_ids": non_public_source_chunks,
        "contact_mismatches": contact_mismatches,
        "invalid_boolean_fields": invalid_boolean_fields,
        "missing_payload_indexes": missing_indexes,
    }

    audit_passed = (
        len(titles) == EXPECTED_DOCUMENT_COUNT
        and len(payloads) == EXPECTED_CHUNK_COUNT
        and not any(bool(value) for value in warnings.values())
        and dense_vector_configured
        and sparse_vector_configured
        and quantization_config is not None
    )

    report = {
        "alias_name": COLLECTION_ALIAS,
        "published_collection": active_collection,
        "expected_document_count": EXPECTED_DOCUMENT_COUNT,
        "actual_document_count": len(titles),
        "expected_chunk_count": EXPECTED_CHUNK_COUNT,
        "actual_chunk_count": len(payloads),
        "unique_document_titles": titles,
        "chunks_per_document": dict(sorted(title_chunk_counts.items())),
        "primary_cohort_counts": dict(primary_tag_counts),
        "contextual_audience_tag_counts": dict(contextual_tag_counts),
        "exception_chunk_count": exception_count,
        "table_chunk_count": table_count,
        "chunking_method_counts": dict(sorted(chunking_method_counts.items())),
        "dense_vector_configured": dense_vector_configured,
        "sparse_vector_configured": sparse_vector_configured,
        "payload_indexes_detected": sorted(indexed_fields),
        "quantization_configured": quantization_config is not None,
        "per_document_summary": document_summaries,
        "warnings": warnings,
        "audit_passed": audit_passed,
    }

    with open(REPORT_PATH, "w", encoding="utf-8") as report_file:
        json.dump(report, report_file, indent=2)

    print("\n" + "=" * 76)
    print("AUDIT RESULT")
    print("=" * 76)
    print(f"Overall status          : {'PASS' if audit_passed else 'REVIEW WARNINGS'}")
    print(f"JSON audit report       : {REPORT_PATH}")
    print(f"Stored title registry   : {TITLES_PATH}")
    print(f"Per-document summary    : {DOCUMENT_SUMMARY_PATH}")
    print("=" * 76)


if __name__ == "__main__":
    audit_database()
