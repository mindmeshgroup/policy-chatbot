import asyncio
import json
import math
import os
from typing import Any

from fastembed import SparseTextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder
from ollama import AsyncClient
from qdrant_client import AsyncQdrantClient, models

from retrieval.config import (
    COLLECTION_ALIAS,
    DENSE_MODEL_NAME,
    DENSE_VECTOR_NAME,
    DENSE_VECTOR_SIZE,
    EXCEPTION_FIELD,
    MAX_EMBED_RETRIES,
    QDRANT_API_KEY,
    QDRANT_URL,
    RERANKER_MODEL_NAME,
    ROLE_FIELD,
    SPARSE_MODEL_NAME,
    SPARSE_VECTOR_NAME,
)
from retrieval.utils.query_rewriter import rewrite_query


# -------------------------------------------------------------------------
# Retrieval configuration
# -------------------------------------------------------------------------

ACTIVE_ROLES = {
    "Student",
    "Staff",
    "Public",
}

STANDARD_PREFETCH_LIMIT = int(
    os.getenv("STANDARD_PREFETCH_LIMIT", "100")
)
EXCEPTION_PREFETCH_LIMIT = int(
    os.getenv("EXCEPTION_PREFETCH_LIMIT", "2")
)
STANDARD_RESULT_LIMIT = int(
    os.getenv("STANDARD_RESULT_LIMIT", "50")
)

STANDARD_DENSE_SCORE_THRESHOLD = float(
    os.getenv("STANDARD_DENSE_SCORE_THRESHOLD", "0.30")
)
STANDARD_SPARSE_SCORE_THRESHOLD = float(
    os.getenv("STANDARD_SPARSE_SCORE_THRESHOLD", "0.30")
)
EXCEPTION_DENSE_SCORE_THRESHOLD = float(
    os.getenv("EXCEPTION_DENSE_SCORE_THRESHOLD", "0.20")
)
EXCEPTION_SPARSE_SCORE_THRESHOLD = float(
    os.getenv("EXCEPTION_SPARSE_SCORE_THRESHOLD", "0.20")
)

# Exception clauses are returned only if they are sufficiently relevant after
# reranking; the setting remains configurable for later calibration.
MIN_EXCEPTION_RERANK_SCORE = float(
    os.getenv("MIN_EXCEPTION_RERANK_SCORE", "0.35")
)
MAX_EXCEPTION_RESULTS = int(
    os.getenv("MAX_EXCEPTION_RESULTS", "2")
)


# -------------------------------------------------------------------------
# Database and model initialisation
# -------------------------------------------------------------------------

client = AsyncQdrantClient(
    url=QDRANT_URL,
    api_key=QDRANT_API_KEY,
)

print("Loading sparse embedding model...")
sparse_model = SparseTextEmbedding(
    model_name=SPARSE_MODEL_NAME
)

print("Loading cross-encoder reranking model...")
reranker = TextCrossEncoder(
    model_name=RERANKER_MODEL_NAME
)


# -------------------------------------------------------------------------
# Role-aware filtering
# -------------------------------------------------------------------------

def normalise_active_role(role: str | None) -> str:
    """
    Maps an incoming account role to one of the broad retrieval roles.

    Guest is treated as Public because it is retained only as contextual
    metadata, not as an active target_cohort value in the current payload.
    """
    candidate_role = (role or "").strip()

    if candidate_role == "Guest":
        return "Public"

    if candidate_role not in ACTIVE_ROLES:
        print(
            f"[SECURITY WARNING] Invalid active role '{candidate_role}'. "
            "Using Public retrieval access."
        )
        return "Public"

    return candidate_role


def get_role_filter(role: str) -> models.Filter:
    """
    Applies the active broad-role hierarchy used for retrieval.

    Staff users may retrieve Student material because they may need to support
    or advise students. Student users do not retrieve Staff-only chunks.
    """
    active_role = normalise_active_role(role)

    if active_role == "Staff":
        allowed_cohorts = ["Staff", "Student", "Public"]
    elif active_role == "Student":
        allowed_cohorts = ["Student", "Public"]
    else:
        allowed_cohorts = ["Public"]

    return models.Filter(
        must=[
            models.FieldCondition(
                key=ROLE_FIELD,
                match=models.MatchAny(any=allowed_cohorts),
            )
        ]
    )


# -------------------------------------------------------------------------
# Early query safeguards
# -------------------------------------------------------------------------

def lacks_semantic_density(question: str) -> bool:
    """
    Rejects questions too short to express a reliable policy retrieval intent.

    This restores the original empty-state behaviour for inputs such as
    'Hello'. One-word policy requests may be supported later through a separate
    UI intent handler, but should not silently retrieve arbitrary evidence now.
    """
    return len(question.split()) < 2


# -------------------------------------------------------------------------
# Query embedding generation
# -------------------------------------------------------------------------

async def generate_dense_query_vector(query: str) -> list[float]:
    """Creates one dense query vector using the same Ollama model as ingestion."""
    last_error: Exception | None = None
    ollama_client = AsyncClient()

    for attempt in range(MAX_EMBED_RETRIES):
        try:
            response = await ollama_client.embed(
                model=DENSE_MODEL_NAME,
                input=query,
            )

            vector = response["embeddings"][0]

            if len(vector) != DENSE_VECTOR_SIZE:
                raise ValueError(
                    f"Dense query vector size mismatch: expected "
                    f"{DENSE_VECTOR_SIZE}, received {len(vector)}."
                )

            return vector

        except Exception as exc:
            last_error = exc
            if attempt < MAX_EMBED_RETRIES - 1:
                await asyncio.sleep(2 ** attempt)

    raise RuntimeError(
        f"Dense query embedding failed after "
        f"{MAX_EMBED_RETRIES} attempts: {last_error}"
    ) from last_error


async def generate_sparse_query_vector(query: str) -> models.SparseVector:
    """Creates one sparse query vector without blocking the async event loop."""
    sparse_outputs = await asyncio.to_thread(
        lambda: list(sparse_model.embed([query]))
    )
    sparse_result = sparse_outputs[0]

    return models.SparseVector(
        indices=sparse_result.indices.tolist(),
        values=sparse_result.values.tolist(),
    )


# -------------------------------------------------------------------------
# Hybrid retrieval tracks
# -------------------------------------------------------------------------

async def fetch_standard_track(
    dense_vector: list[float],
    sparse_vector: models.SparseVector,
    role_filter: models.Filter,
):
    """Runs dense/sparse fusion over role-allowed policy chunks."""
    return await client.query_points(
        collection_name=COLLECTION_ALIAS,
        prefetch=[
            models.Prefetch(
                query=dense_vector,
                using=DENSE_VECTOR_NAME,
                filter=role_filter,
                limit=STANDARD_PREFETCH_LIMIT,
                score_threshold=STANDARD_DENSE_SCORE_THRESHOLD,
                params=models.SearchParams(
                    quantization=models.QuantizationSearchParams(
                        ignore=False,
                        rescore=True,
                        oversampling=3.0,
                    )
                ),
            ),
            models.Prefetch(
                query=sparse_vector,
                using=SPARSE_VECTOR_NAME,
                filter=role_filter,
                limit=STANDARD_PREFETCH_LIMIT,
                score_threshold=STANDARD_SPARSE_SCORE_THRESHOLD,
            ),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=STANDARD_RESULT_LIMIT,
    )


async def fetch_exception_track(
    dense_vector: list[float],
    sparse_vector: models.SparseVector,
    role_filter: models.Filter,
):
    """Runs an additional small search for relevant exception clauses."""
    exception_filter = models.Filter(
        must=[
            *role_filter.must,
            models.FieldCondition(
                key=EXCEPTION_FIELD,
                match=models.MatchValue(value=True),
            ),
        ]
    )

    return await client.query_points(
        collection_name=COLLECTION_ALIAS,
        prefetch=[
            models.Prefetch(
                query=dense_vector,
                using=DENSE_VECTOR_NAME,
                filter=exception_filter,
                limit=EXCEPTION_PREFETCH_LIMIT,
                score_threshold=EXCEPTION_DENSE_SCORE_THRESHOLD,
                params=models.SearchParams(
                    quantization=models.QuantizationSearchParams(
                        ignore=False,
                        rescore=True,
                        oversampling=3.0,
                    )
                ),
            ),
            models.Prefetch(
                query=sparse_vector,
                using=SPARSE_VECTOR_NAME,
                filter=exception_filter,
                limit=EXCEPTION_PREFETCH_LIMIT,
                score_threshold=EXCEPTION_SPARSE_SCORE_THRESHOLD,
            ),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=EXCEPTION_PREFETCH_LIMIT,
    )


def deduplicate_points(points: list[Any]) -> list[Any]:
    """Removes chunks retrieved by both ordinary and exception retrieval tracks."""
    unique_points: dict[str, Any] = {}

    for point in points:
        payload = point.payload or {}
        result_key = str(payload.get("chunk_id") or getattr(point, "id", ""))

        existing = unique_points.get(result_key)
        if existing is None:
            unique_points[result_key] = point
            continue

        current_score = float(getattr(point, "score", 0.0) or 0.0)
        existing_score = float(getattr(existing, "score", 0.0) or 0.0)

        if current_score > existing_score:
            unique_points[result_key] = point

    return list(unique_points.values())


async def rerank_candidates(
    question: str,
    points: list[Any],
) -> list[tuple[Any, float]]:
    """Reranks retrieved evidence chunks using the local cross-encoder."""
    if not points:
        return []

    documents = []
    for point in points:
        payload = point.payload or {}
        documents.append(
            "Title: "
            f"{payload.get('document_title', 'Unknown Document')}\n"
            "Section: "
            f"{payload.get('breadcrumb', '')}\n"
            "Content: "
            f"{payload.get('content', '')}"
        )

    raw_scores = await asyncio.to_thread(
        lambda: list(reranker.rerank(question, documents))
    )

    ranked_points = []
    for point, raw_score in zip(points, raw_scores):
        bounded_logit = max(min(float(raw_score), 100.0), -100.0)
        probability_score = 1 / (1 + math.exp(-bounded_logit))
        ranked_points.append((point, probability_score))

    ranked_points.sort(
        key=lambda item: item[1],
        reverse=True,
    )
    return ranked_points


def select_final_points(
    ranked_points: list[tuple[Any, float]],
    max_k: int,
) -> list[tuple[Any, float]]:
    """
    Selects standard evidence and relevant exception clauses after reranking.
    """
    standard_results: list[tuple[Any, float]] = []
    exception_results: list[tuple[Any, float]] = []

    for point, score in ranked_points:
        payload = point.payload or {}
        is_exception = payload.get(EXCEPTION_FIELD) is True

        if is_exception:
            if (
                score >= MIN_EXCEPTION_RERANK_SCORE
                and len(exception_results) < MAX_EXCEPTION_RESULTS
            ):
                exception_results.append((point, score))
        elif len(standard_results) < max_k:
            standard_results.append((point, score))

    return standard_results + exception_results


def format_results(
    selected_points: list[tuple[Any, float]],
) -> list[dict]:
    """Returns evidence chunks and citation metadata for answer generation."""
    formatted_results = []

    for point, rerank_score in selected_points:
        payload = point.payload or {}

        formatted_results.append({
            "score": round(rerank_score, 4),
            "content": payload.get("content", ""),
            "has_table": payload.get("has_table", False),
            "is_exception": payload.get(EXCEPTION_FIELD, False),
            "document_title": payload.get("document_title", "Unknown Document"),
            "source_url": payload.get("source_url", ""),
            "enquiries_contact": payload.get("enquiries_contact", {}),
            "escalation_contact": payload.get("escalation_contact", "Ask La Trobe"),
            "breadcrumb": payload.get("breadcrumb", ""),
            "document_summary": payload.get("document_summary", ""),
            "doc_type": payload.get("doc_type", "Policy"),
            "category": payload.get("category", "La Trobe Policy Library"),
            "access_level": payload.get("access_level", ""),
            "target_cohort": payload.get(ROLE_FIELD, []),
            "contextual_audience_tags": payload.get("contextual_audience_tags", []),
            "campus_scope": payload.get("campus_scope", []),
            "document_id": payload.get("document_id", ""),
            "canonical_document_id": payload.get("canonical_document_id", ""),
            "approval_body": payload.get("approval_body"),
            "department_owner": payload.get("department_owner", {}),
            "status": payload.get("status"),
            "effective_date_iso": payload.get("effective_date_iso"),
            "review_date": payload.get("review_date"),
            "chunk_id": payload.get("chunk_id", ""),
            "chunk_index": payload.get("chunk_index", 0),
            "chunk_type": payload.get("chunk_type", "Text"),
            "chunking_method": payload.get("chunking_method", ""),
        })

    return formatted_results


# -------------------------------------------------------------------------
# Public retrieval entry point
# -------------------------------------------------------------------------

async def retrieve_policies(
    question: str,
    role: str = "Student",
    max_k: int = 3,
) -> list[dict]:
    """
    Retrieves role-allowed evidence from the promoted policy collection.

    Query rewriting improves the search expression only. Access is controlled
    solely by the trusted account role supplied to this function.
    """
    cleaned_question = question.strip()

    if not cleaned_question:
        return []

    if lacks_semantic_density(cleaned_question):
        print(
            f"[REJECTED] Query '{cleaned_question}' "
            "lacks sufficient semantic density."
        )
        return []

    if max_k < 1:
        raise ValueError("max_k must be at least 1.")

    active_role = normalise_active_role(role)

    print(f"\n[RETRIEVAL] Raw user query: {cleaned_question!r}")
    print(f"  [ROLE FILTER] Active retrieval role: {active_role}")

    rewritten = await rewrite_query(
        cleaned_question,
        active_role,
    )

    if not rewritten.get("requires_policy_retrieval", True):
        print(
            "  [REJECTED] Query is outside the scope of the university "
            "policy knowledge base."
        )
        return []

    print(f"  [REWRITER] Cleaned:   {rewritten['cleaned_query']}")
    print(f"  [REWRITER] Technical: {rewritten['technical_query']}")
    print(f"  [REWRITER] Step-back: {rewritten['step_back_query']}")

    if rewritten["contextual_audience_hints"]:
        print(
            "  [REWRITER] Context hints only: "
            f"{rewritten['contextual_audience_hints']}"
        )

    # Keep the original words alongside rewritten forms so a poor paraphrase
    # cannot erase important terms such as "personal work" or "falsifying".
    semantic_query = " ".join([
        cleaned_question,
        rewritten["technical_query"],
        rewritten["step_back_query"],
    ]).strip()

    keyword_query = " ".join([
        cleaned_question,
        rewritten["cleaned_query"],
        rewritten["technical_query"],
    ]).strip()

    try:
        dense_vector, sparse_vector = await asyncio.gather(
            generate_dense_query_vector(semantic_query),
            generate_sparse_query_vector(keyword_query),
        )
    except Exception as exc:
        print(f"[ERROR] Query embedding generation failed: {exc}")
        return []

    role_filter = get_role_filter(active_role)

    try:
        standard_response, exception_response = await asyncio.gather(
            fetch_standard_track(dense_vector, sparse_vector, role_filter),
            fetch_exception_track(dense_vector, sparse_vector, role_filter),
        )
    except Exception as exc:
        print(f"[ERROR] Qdrant retrieval failed: {exc}")
        return []

    candidate_points = deduplicate_points(
        list(standard_response.points)
        + list(exception_response.points)
    )

    print(
        "  [RETRIEVAL] Unique candidate chunks before reranking: "
        f"{len(candidate_points)}"
    )

    try:
        ranked_points = await rerank_candidates(
            cleaned_question,
            candidate_points,
        )
    except Exception as exc:
        print(f"[ERROR] Candidate reranking failed: {exc}")
        return []

    if not ranked_points:
        print(
            "  [REJECTED] No policy evidence was retrieved. "
            "Returning an empty result."
        )
        return []

    selected_points = select_final_points(
        ranked_points,
        max_k,
    )

    return format_results(selected_points)


# -------------------------------------------------------------------------
# Manual retrieval smoke test for the currently promoted ten-policy collection
# -------------------------------------------------------------------------

async def run_all_tests() -> None:
    """
    Checks direct retrieval, query rewriting and empty-state safeguards.

    These are integration smoke tests only; they are not the final Recall@K or
    MRR evaluation dataset.
    """
    test_queries = [
        ("How quickly must I report a privacy data breach?", "Student"),
        ("Do students own the IP they create?", "Student"),
        ("What is the maximum number of days for paid personal work?", "Staff"),
        ("What does the Records Management Policy require for university records?", "Staff"),
        ("i got fired and want to apeal my termnation, how do i do that?", "Staff"),
        ("can i start a side hustle or freelance gig if I work here full time?", "Staff"),
        ("as a phd student, who gets to be the first author on my thesis paper?", "Student"),
        ("what happens if an academic gets caught falsifying their grant data?", "Staff"),
        ("Where can I find a good pepperoni pizza?", "Student"),
        ("Hello", "Student"),
    ]

    all_results = {}

    for query, role in test_queries:
        print("\n" + "=" * 60)
        print(f"Running retrieval for: {query!r} | Role: {role}")
        print("=" * 60)

        all_results[query] = await retrieve_policies(
            query,
            role=role,
        )

    with open("test_results.json", "w", encoding="utf-8") as file:
        json.dump(all_results, file, indent=2)

    print("\nRetrieval smoke test complete. Open test_results.json for results.")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
