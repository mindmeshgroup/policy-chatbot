import datetime

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    KeywordIndexParams,
    ScalarQuantization,
    ScalarQuantizationConfig,
    ScalarType,
    SparseVectorParams,
    VectorParams,
)

from retrieval.config import (
    QDRANT_API_KEY,
    QDRANT_URL,
    DENSE_VECTOR_NAME,
    DENSE_VECTOR_SIZE,
    SPARSE_VECTOR_NAME,
)


def create_candidate_collection() -> str:
    """
    Creates an empty candidate collection for a complete policy-library rebuild.

    The live alias is not changed here. It should be promoted only after all
    selected policies have been inserted and checked successfully.
    """
    client = QdrantClient(
        url=QDRANT_URL,
        api_key=QDRANT_API_KEY,
    )

    timestamp = datetime.datetime.now(
        datetime.timezone.utc
    ).strftime("%Y%m%d_%H%M%S_%f")

    collection_name = f"policies_{timestamp}"

    print("=====================================================")
    print("   CREATING QDRANT CANDIDATE COLLECTION")
    print("=====================================================")
    print(f"[*] Creating candidate collection: {collection_name}...")

    # Store both semantic and keyword-aware vectors for hybrid retrieval.
    client.create_collection(
        collection_name=collection_name,
        vectors_config={
            DENSE_VECTOR_NAME: VectorParams(
                size=DENSE_VECTOR_SIZE,
                distance=Distance.COSINE,
                on_disk=True,
            )
        },
        sparse_vectors_config={
            SPARSE_VECTOR_NAME: SparseVectorParams()
        },
        quantization_config=ScalarQuantization(
            scalar=ScalarQuantizationConfig(
                type=ScalarType.INT8,
                always_ram=True,
            )
        ),
    )

    print("[*] Building payload indexes before policy insertion...")

    # Used when equivalent HTML and PDF versions of one policy are compared.
    client.create_payload_index(
        collection_name=collection_name,
        field_name="canonical_document_id",
        field_schema=KeywordIndexParams(
            type="keyword",
            on_disk=True,
        ),
    )

    # Used by the current broad audience filter during retrieval.
    client.create_payload_index(
        collection_name=collection_name,
        field_name="target_cohort",
        field_schema=KeywordIndexParams(
            type="keyword",
            on_disk=False,
        ),
    )

    # Stored as a Boolean because each chunk either includes an exception or does not.
    client.create_payload_index(
        collection_name=collection_name,
        field_name="is_exception",
        field_schema="bool",
    )

    # Records whether the original source page was publicly accessible.
    client.create_payload_index(
        collection_name=collection_name,
        field_name="access_level",
        field_schema=KeywordIndexParams(
            type="keyword",
            on_disk=False,
        ),
    )

    print(f"[*] Candidate collection ready for ingestion: {collection_name}")
    return collection_name


if __name__ == "__main__":
    new_collection = create_candidate_collection()
    print(
        f"[*] Insert and test validated policy chunks in '{new_collection}' "
        "before promoting it to the live alias."
    )
