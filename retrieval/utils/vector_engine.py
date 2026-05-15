import ollama
import uuid
import hashlib
import re
from urllib.parse import urlparse
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue, SparseVector
from fastembed import SparseTextEmbedding

# CONFIGURATION 
QDRANT_URL = "http://localhost:6333"
EMBED_MODEL = "nomic-embed-text"

DENSE_NAME = "text-dense" 
SPARSE_NAME = "text-sparse"

client = QdrantClient(url=QDRANT_URL)

# Sparse Embedding Model (SPLADE)
print("Loading Sparse Embedding Model (SPLADE)...")
sparse_model = SparseTextEmbedding(model_name="prithivida/Splade_PP_en_v1")

# --- NEW: Semantic Title Hasher ---
def generate_universal_id(document_title: str) -> str:
    """Generates a universal ID based purely on the text of the policy title."""
    clean_title = document_title.lower()
    clean_title = re.sub(r'[^a-z0-9]', '', clean_title) # Strip punctuation/spaces
    return hashlib.md5(clean_title.encode('utf-8')).hexdigest()[:12]

def get_dense_embedding(text):
    """Converts text into a 768-dimension vector using Ollama."""
    response = ollama.embeddings(model=EMBED_MODEL, prompt=text)
    return response['embedding']

def get_sparse_embedding(text):
    """Converts text into a sparse index-value dictionary using FastEmbed."""
    sparse_generator = list(sparse_model.embed([text]))
    sparse_result = sparse_generator[0]
    
    return SparseVector(
        indices=sparse_result.indices.tolist(),
        values=sparse_result.values.tolist()
    )

# --- UPDATED: Added source_path argument ---
def clean_and_upsert(collection_name, payloads, source_path):
    """Phase 5: The Vector Vault """
    if not payloads:
        return
    
    # 1. Generate Universal ID based on the Title
    policy_title = payloads[0].get('document_title', 'Unknown Policy')
    doc_id = generate_universal_id(policy_title)
    
    # Force all chunks to use this universal ID
    for p in payloads:
        p['document_id'] = doc_id 
        
    print(f"3. Validating Qdrant existing data for: '{policy_title}' (ID: {doc_id})...")
    
    # --- NEW: HTML Dominance Check ---
    existing_points = client.scroll(
        collection_name=collection_name,
        scroll_filter=Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=doc_id))]),
        limit=1,
        with_payload=True
    )[0] 
    
    if existing_points:
        existing_format = existing_points[0].payload.get('source_url', '')
        
        # Scenario A: Block the PDF
        if source_path.endswith('.pdf') and ('.html' in existing_format or 'view.php' in existing_format):
            print(f"   -> [SKIP] Ignored {source_path}. An HTML version already exists in Qdrant.")
            return
            
        # Scenario B: Upgrade
        elif (source_path.endswith('.html') or 'view.php' in source_path) and '.pdf' in existing_format:
            print(f"   -> [UPGRADE] Replacing older PDF chunks with the HTML web scrape!")
    # 2. Delete old data first to avoid duplicates (Overwrites if updating)
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
        
        # Generate both vectors
        dense_vec = get_dense_embedding(chunk_text)
        sparse_vec = get_sparse_embedding(chunk_text)
        
        # Package both vectors with their correct keys
        points.append(PointStruct(
            id=str(uuid.uuid4()),
            vector={
                DENSE_NAME: dense_vec,
                SPARSE_NAME: sparse_vec
            }, 
            payload=p
        ))

    # Upsert to Database
    client.upsert(collection_name=collection_name, points=points)
    print(f"--- SUCCESS: {len(points)} Hybrid points saved to Qdrant ---")