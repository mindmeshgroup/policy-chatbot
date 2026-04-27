from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, 
    VectorParams, 
    SparseVectorParams, 
    ScalarQuantization,
    ScalarQuantizationConfig,
    ScalarType,
    KeywordIndexParams, 
    BoolIndexParams, 
    DatetimeIndexParams
)

# docker container
client = QdrantClient(url="http://localhost:6333")

COLLECTION_NAME = "university_policies"

def initialise_database():
    print("Connecting to Qdrant Docker container...")
    
    # reset the vault if it exists
    if client.collection_exists(COLLECTION_NAME):
        print(f"Resetting collection '{COLLECTION_NAME}'...")
        client.delete_collection(COLLECTION_NAME)

    # hybrid Collection
    print(f"Creating Hybrid-Search collection: '{COLLECTION_NAME}'...")
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={
            # DENSE: Ollama's 'nomic-embed-text' model
            "text-dense": VectorParams(
                size=768, 
                distance=Distance.COSINE,
                on_disk=True  
            )
        },
        sparse_vectors_config={
            # SPARSE: FastEmbed 'Splade' keyword matching
            "text-sparse": SparseVectorParams()
        },
        # INT8 SCALAR QUANTIZATION CONFIGURATION 
        quantization_config=ScalarQuantization(
            scalar=ScalarQuantizationConfig(
                type=ScalarType.INT8,
                quantile=0.99,     # Ignores the top 1% of outliers for better compression
                always_ram=True    
            )
        )
    )


   # payload indexes
    print("Creating Payload Indexes...")
    
   
    
    # 1. abac and administrative keywords (on-disk)
    keyword_fields = ["document_id", "target_cohort", "access_level", "category", "doc_type"]
    for field in keyword_fields:
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name=field,
            field_schema=KeywordIndexParams(
                type="keyword",
                on_disk=True 
            )
        )

    # 2. CRAG expectuion flag (on-disk)
    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="is_exception",
        field_schema=BoolIndexParams(
            type="bool",
            on_disk=True
        )
    )

    # 3. date filtering (by effective date)
    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="effective_date_iso",
        field_schema=DatetimeIndexParams(
            type="datetime",
            on_disk=True,
            is_principal=True
        )
    )
    
    print(f"Database successfully initialised with Quantization and Payload Indices.")

if __name__ == "__main__":
    initialise_database()