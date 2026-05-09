import os
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
    DatetimeIndexParams,
    HnswConfigDiff 
)

# Connects to localhost by default, but uses a cloud URL and API key if deployed
client = QdrantClient(
    url=os.getenv("QDRANT_URL", "http://localhost:6333"),
    api_key=os.getenv("QDRANT_API_KEY", None)
)

COLLECTION_NAME = "university_policies"

def initialise_database():
    print("Connecting to Qdrant Docker container...")
    
    try:
        # reset the vault if it exists
        if client.collection_exists(COLLECTION_NAME):
            # prevent accidental database wipes
            confirm = input(f"WARNING: Collection '{COLLECTION_NAME}' exists. Type 'YES/yes' to delete and rebuild: ")
            confirm = confirm.upper()
            if confirm == 'YES':
                print(f"Resetting collection '{COLLECTION_NAME}'...")
                client.delete_collection(COLLECTION_NAME)
            else:
                print("Aborting database setup.")
                return

        # hybrid Collection
        print(f"Creating Hybrid-Search collection: '{COLLECTION_NAME}'...")
        client.create_collection(
            collection_name=COLLECTION_NAME,
            # GRAPH TUNING: Denser graph for better accuracy/recall to prevent LLM hallucinations
            hnsw_config=HnswConfigDiff(
                m=32,                 # Default is 16. Higher = denser graph, better recall
                ef_construct=200      # Default is 100. Slower to build, but much more accurate search
            ),
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
        # Added department_owner and chunk_type for future-proofing
        keyword_fields = ["document_id", "target_cohort", "access_level", "category", "doc_type", "department_owner", "chunk_type"]
        for field in keyword_fields:
            client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name=field,
                field_schema=KeywordIndexParams(
                    type="keyword",
                    on_disk=True 
                )
            )

        # 2. CRAG exception flag (on-disk)
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
                on_disk=True
            )
        )
        
        print(f"Database successfully initialised with Quantisation and Payload Indices.")
        
    except Exception as e:
        # CRASH ERROR RISK MITIGATION: Handles Docker drops or connection timeouts gracefully
        print("\n[ERROR] Failed to connect to or initialise the Qdrant database.")
        print(f"Details: {e}")
        print("Please ensure your local Docker container is running on port 6333 or your environment variables are set correctly.")

if __name__ == "__main__":
    initialise_database()