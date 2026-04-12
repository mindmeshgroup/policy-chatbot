import ollama
import uuid
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue, SparseVector
from fastembed import SparseTextEmbedding

# --- CONFIGURATION ---
QDRANT_URL = "http://localhost:6333"
EMBED_MODEL = "nomic-embed-text"

# Matches the names defined in retrieval/setup_db.py
DENSE_NAME = "text-dense" 
SPARSE_NAME = "text-sparse"

client = QdrantClient(url=QDRANT_URL)

# Initialize the Sparse Embedding Model (SPLADE)
print("Loading Sparse Embedding Model (SPLADE)...")
sparse_model = SparseTextEmbedding(model_name="prithivida/Splade_PP_en_v1")

def get_dense_embedding(text):
    """Converts text into a 768-dimension vector using Ollama."""
    response = ollama.embeddings(model=EMBED_MODEL, prompt=text)
    return response['embedding']

def get_sparse_embedding(text):
    """Converts text into a sparse index-value dictionary using FastEmbed."""
    # FastEmbed expects a list of strings, so we wrap the text in brackets
    sparse_generator = list(sparse_model.embed([text]))
    sparse_result = sparse_generator[0]
    
    return SparseVector(
        indices=sparse_result.indices.tolist(),
        values=sparse_result.values.tolist()
    )

def clean_and_upsert(collection_name, payloads):
    """Phase 5: The Vector Vault (The 'Clean Sweep' Strategy)"""
    if not payloads:
        return
    
    doc_id = payloads[0]['document_id']
    print(f"3. Cleaning existing data for Document ID: {doc_id}...")
    
    # Delete old data first to avoid duplicates
    client.delete(
        collection_name=collection_name,
        points_selector=Filter(
            must=[FieldCondition(key="document_id", match=MatchValue(value=doc_id))]
        )
    )

    print(f"4. Generating DENSE and SPARSE embeddings for {len(payloads)} points...")
    points = []
    
    for p in payloads:
        chunk_text = p['content']
        
        # 1. Generate both vectors
        dense_vec = get_dense_embedding(chunk_text)
        sparse_vec = get_sparse_embedding(chunk_text)
        
        # 2. Package both vectors with their correct keys
        points.append(PointStruct(
            id=str(uuid.uuid4()),
            vector={
                DENSE_NAME: dense_vec,
                SPARSE_NAME: sparse_vec
            }, 
            payload=p
        ))

    # 3. Upsert to Database
    client.upsert(collection_name=collection_name, points=points)
    print(f"--- SUCCESS: {len(points)} Hybrid points saved to Qdrant ---")