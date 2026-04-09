# retrieval/setup_db.py

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, SparseVectorParams, PayloadSchemaType

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
                distance=Distance.COSINE
            )
        },
        sparse_vectors_config={
            # SPARSE: FastEmbed 'Splade' keyword matching
            "text-sparse": SparseVectorParams()
        }
    )

    # payload indexes
    print("Creating Payload Indexes")
    
    # layer 4: administrative group
    # this allows ingest.py to quickly find and delete old versions of a document
    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="document_id",
        field_schema=PayloadSchemaType.KEYWORD,
    )

    # layer 4 : validation group (for backend filtering)
    # these indexes allow retrieval.py to instantly filter out unauthorised chunks
    
    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="target_cohort", # e.g., ["Student", "Staff"]
        field_schema=PayloadSchemaType.KEYWORD,
    )
    
    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="access_level", # e.g., "Public", "Staff Only"
        field_schema=PayloadSchemaType.KEYWORD,
    )

    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="category", # e.g., "Academic", "Assessment"
        field_schema=PayloadSchemaType.KEYWORD,
    )
    
    client.create_payload_index(
        collection_name=COLLECTION_NAME,
        field_name="doc_type", # e.g., "Policy", "Procedure"
        field_schema=PayloadSchemaType.KEYWORD,
    )

    print("Database successfully initialised")

if __name__ == "__main__":
    initialise_database()