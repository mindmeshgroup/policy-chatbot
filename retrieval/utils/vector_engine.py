import uuid
import time
import hashlib
import re
import ollama
from concurrent.futures import ThreadPoolExecutor
from qdrant_client import QdrantClient
from qdrant_client.models import (
    PointStruct,
    Filter,
    FilterSelector,
    FieldCondition,
    MatchValue,
    SparseVector,
)
from fastembed import SparseTextEmbedding

# Read shared settings from one configuration file so that collection setup,
# vector insertion and retrieval use the same model and vector definitions.
from retrieval.config import (
    QDRANT_URL,
    QDRANT_API_KEY,
    DENSE_MODEL_NAME,
    DENSE_VECTOR_SIZE,
    DENSE_VECTOR_NAME,
    SPARSE_MODEL_NAME,
    SPARSE_VECTOR_NAME,
    MAX_EMBED_RETRIES,
    MAX_DENSE_EMBED_WORKERS,
)

# -------------------------------------------------------------------------
# Database connection and embedding model setup
# -------------------------------------------------------------------------

# Connect to the Qdrant instance that stores validated policy chunks.
client = QdrantClient(
    url=QDRANT_URL,
    api_key=QDRANT_API_KEY,
)

# The sparse model is loaded only when insertion begins, because loading it
# during module import would use memory even when the file is not yet needed.
sparse_model = None


def get_sparse_model():
    """
    Loads the sparse embedding model once and reuses it during this ingestion run.
    """
    global sparse_model

    if sparse_model is None:
        print("   -> Loading sparse embedding model for this ingestion process...")
        sparse_model = SparseTextEmbedding(
            model_name=SPARSE_MODEL_NAME
        )

    return sparse_model


def generate_canonical_document_id(document_title: str) -> str:
    """
    Creates a stable grouping identifier from the official policy title.

    This allows HTML and PDF versions of the same policy to be recognised
    as equivalent source versions during database insertion.
    """
    normalised_title = re.sub(
        r"[^a-z0-9]+",
        "",
        document_title.casefold(),
    )

    if not normalised_title:
        raise ValueError(
            "Cannot generate canonical document ID from an empty title."
        )

    return hashlib.sha256(
        normalised_title.encode("utf-8")
    ).hexdigest()[:12]


def get_dense_embedding(text: str) -> list[float]:
    """
    Generates one dense semantic embedding using the local Ollama model.

    Temporary embedding failures are retried so that a short local service
    interruption does not immediately stop insertion for the whole document.
    """
    last_error: Exception | None = None

    for attempt in range(MAX_EMBED_RETRIES):
        try:
            response = ollama.embed(
                model=DENSE_MODEL_NAME,
                input=text,
            )

            embedding = response["embeddings"][0]

            if not embedding:
                raise RuntimeError(
                    "Ollama returned an empty embedding vector."
                )

            return embedding

        except Exception as exc:
            last_error = exc

            if attempt < MAX_EMBED_RETRIES - 1:
                time.sleep(2 ** attempt)

    raise RuntimeError(
        f"Dense embedding generation failed after "
        f"{MAX_EMBED_RETRIES} attempts: {last_error}"
    ) from last_error


# -------------------------------------------------------------------------
# Validated payload insertion into Qdrant
# -------------------------------------------------------------------------

def clean_and_upsert(
    collection_name: str,
    payloads: list[dict],
    max_dense_workers: int | None = None,
):
    """
    Converts validated policy chunks into hybrid vectors and stores them in Qdrant.

    The function processes one policy document at a time, prefers an available
    HTML source over an older PDF copy, and replaces earlier stored chunks only
    after all new vectors have been generated successfully.

    When multiple policy documents are inserted in parallel by the orchestrator,
    max_dense_workers can limit the number of dense requests issued inside each
    individual worker process.
    """
    if not payloads:
        return

    dense_worker_limit = (
        MAX_DENSE_EMBED_WORKERS
        if max_dense_workers is None
        else max_dense_workers
    )

    if dense_worker_limit < 1:
        raise ValueError("max_dense_workers must be at least 1.")

    # Ensure one insertion batch contains chunks from only one policy.
    # This prevents replacement logic from deleting chunks belonging to
    # an unrelated document.
    document_ids = {
        payload.get("document_id")
        for payload in payloads
    }

    document_titles = {
        payload.get("document_title")
        for payload in payloads
    }

    canonical_ids = {
        payload.get("canonical_document_id")
        for payload in payloads
    }

    if None in document_ids or len(document_ids) != 1:
        raise ValueError(
            "Upsert batch must contain chunks from exactly one validated document."
        )

    if None in document_titles or len(document_titles) != 1:
        raise ValueError(
            "Upsert batch contains inconsistent document titles."
        )

    if None in canonical_ids or len(canonical_ids) != 1:
        raise ValueError(
            "Upsert batch contains missing or inconsistent canonical document IDs."
        )

    policy_title = next(iter(document_titles))
    document_id = next(iter(document_ids))
    canonical_document_id = next(iter(canonical_ids))

    # Recalculate the title-based grouping ID to confirm that the validated
    # metadata has remained consistent before insertion.
    expected_canonical_id = generate_canonical_document_id(
        policy_title
    )

    if canonical_document_id != expected_canonical_id:
        raise ValueError(
            f"Canonical document ID does not match the document title for "
            f"'{policy_title}'. Expected '{expected_canonical_id}', "
            f"received '{canonical_document_id}'."
        )

    # Look for an existing version of the same policy so that the HTML
    # source can be kept in preference to an equivalent PDF version.
    existing_points, _ = client.scroll(
        collection_name=collection_name,
        scroll_filter=Filter(
            must=[
                FieldCondition(
                    key="canonical_document_id",
                    match=MatchValue(
                        value=canonical_document_id
                    ),
                )
            ]
        ),
        limit=1000,
        with_payload=["source_url"],
    )

    if existing_points:
        incoming_source_url = str(
            payloads[0].get("source_url", "")
        ).casefold()

        incoming_is_html = (
            "view.php" in incoming_source_url
            or incoming_source_url.endswith(".html")
        )

        incoming_is_pdf = (
            incoming_source_url.endswith(".pdf")
            or "download.php" in incoming_source_url
        )

        existing_source_urls = {
            str(point.payload.get("source_url", "")).casefold()
            for point in existing_points
        }

        existing_has_html = any(
            "view.php" in url or url.endswith(".html")
            for url in existing_source_urls
        )

        existing_has_pdf = any(
            url.endswith(".pdf") or "download.php" in url
            for url in existing_source_urls
        )

        # Keep the already indexed HTML source instead of inserting a
        # duplicate PDF version of the same policy.
        if incoming_is_pdf and existing_has_html:
            print(
                f"   -> [SKIP] Ignored '{policy_title}' because "
                "an HTML version already exists."
            )
            return

        # Allow an HTML source to replace older chunks that came from a PDF.
        if incoming_is_html and existing_has_pdf:
            print(
                "   -> [UPGRADE] Replacing older PDF chunks "
                "with the HTML source."
            )

    print(
        f"4. Generating dense and sparse embeddings "
        f"for {len(payloads)} chunks..."
    )

    all_texts = [
        payload["content"]
        for payload in payloads
    ]

    # Generate sparse vectors in one batch to support exact-term and
    # keyword-aware retrieval for policy names, codes and rule wording.
    model = get_sparse_model()
    sparse_results_list = list(
        model.embed(all_texts)
    )

    # Generate dense vectors through a small controlled thread pool so local
    # embedding is faster without sending too many requests to Ollama at once.
    print("   -> Sending embedding requests to Ollama...")

    with ThreadPoolExecutor(
        max_workers=dense_worker_limit
    ) as executor:
        dense_results_list = list(
            executor.map(get_dense_embedding, all_texts)
        )

    points = []

    # Combine each validated metadata payload with its dense and sparse vectors.
    for index, payload in enumerate(payloads):
        dense_vec = dense_results_list[index]
        sparse_result = sparse_results_list[index]

        # Check that the embedding model output matches the vector size used
        # when the Qdrant collection was created.
        if len(dense_vec) != DENSE_VECTOR_SIZE:
            raise ValueError(
                f"Dense embedding size mismatch for chunk "
                f"'{payload['chunk_id']}': expected {DENSE_VECTOR_SIZE}, "
                f"received {len(dense_vec)}."
            )

        sparse_vector = SparseVector(
            indices=sparse_result.indices.tolist(),
            values=sparse_result.values.tolist(),
        )

        # Create a stable point ID so rerunning insertion updates the same
        # chunk instead of storing duplicate vector records.
        deterministic_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{document_id}:{payload['chunk_id']}",
            )
        )

        points.append(
            PointStruct(
                id=deterministic_id,
                vector={
                    DENSE_VECTOR_NAME: dense_vec,
                    SPARSE_VECTOR_NAME: sparse_vector,
                },
                payload=payload,
            )
        )

    # Delete the earlier stored version only after all replacement points
    # have been prepared and checked successfully.
    client.delete(
        collection_name=collection_name,
        points_selector=FilterSelector(
            filter=Filter(
                must=[
                    FieldCondition(
                        key="canonical_document_id",
                        match=MatchValue(
                            value=canonical_document_id
                        ),
                    )
                ]
            )
        ),
        wait=True,
    )

    # Insert the completed hybrid-vector payloads into the candidate collection.
    client.upsert(
        collection_name=collection_name,
        points=points,
        wait=True,
    )

    print(
        f"   -> SUCCESS: {len(points)} hybrid points saved to Qdrant."
    )
