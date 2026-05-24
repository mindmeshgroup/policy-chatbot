import ollama
import uuid
import hashlib
import re
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue, SparseVector
from fastembed import SparseTextEmbedding

# CONFIGURATION 
QDRANT_URL = "http://localhost:6333"
EMBED_MODEL = "nomic-embed-text"

DENSE_NAME = "text-dense" 
SPARSE_NAME = "text-sparse"

client = QdrantClient(url=QDRANT_URL)

# --- FIX 1: Lazy-Load Global Initialization ---
sparse_model = None

def get_sparse_model():
    """Lazy-loads the model only when the specific CPU worker needs it."""
    global sparse_model
    if sparse_model is None:
        print("Loading Sparse Embedding Model (SPLADE) for worker...")
        sparse_model = SparseTextEmbedding(model_name="prithivida/Splade_PP_en_v1")
    return sparse_model

# --- Semantic Title Hasher ---
def generate_universal_id(document_title: str) -> str:
    """Generates a universal ID based purely on the text of the policy title."""
    clean_title = document_title.lower()
    clean_title = re.sub(r'[^a-z0-9]', '', clean_title) 
    return hashlib.md5(clean_title.encode('utf-8')).hexdigest()[:12]

def get_dense_embedding(text):
    """Converts text into a 768-dimension vector using Ollama."""
    response = ollama.embeddings(model=EMBED_MODEL, prompt=text)
    return response['embedding']

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
        
    print(f"3. Validating Qdrant existing data for: '{policy_title}'...")
    
    # --- HTML DOMINANCE CHECK ---
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
            
        # Scenario B: Announce the Upgrade!
        elif (source_path.endswith('.html') or 'view.php' in source_path) and '.pdf' in existing_format:
            print(f"   -> [UPGRADE] Replacing older PDF chunks with the HTML web scrape!")
    
    # --- FIX 4: The "Mixed Payload" Deletion ---
    doc_ids_to_clean = list(set([p['document_id'] for p in payloads]))
    
    for current_doc_id in doc_ids_to_clean:
        client.delete(
            collection_name=collection_name,
            points_selector=Filter(
                must=[FieldCondition(key="document_id", match=MatchValue(value=current_doc_id))]
            )
        )

    print(f"4. Generating DENSE and SPARSE embeddings for {len(payloads)} chunks...")
    points = []
    
    # Extract all texts into a single list
    all_texts = [p['content'] for p in payloads]
    
    # --- PHASE A: CPU-Bound Batching (Sparse) ---
    model = get_sparse_model()
    sparse_results_list = list(model.embed(all_texts))
    
    # --- PHASE B: I/O-Bound Threading (Dense) ---
    print(f"   -> Sending concurrent embedding requests to Ollama...")
    with ThreadPoolExecutor(max_workers=10) as executor:
        dense_results_list = list(executor.map(get_dense_embedding, all_texts))
    
    # --- PHASE C: Zipping and Packaging ---
    for i, p in enumerate(payloads):
        # Grab the pre-computed vectors from our arrays
        dense_vec = dense_results_list[i]
        sparse_result = sparse_results_list[i]
        
        sparse_vec = SparseVector(
            indices=sparse_result.indices.tolist(),
            values=sparse_result.values.tolist()
        )
        
        # --- FIX 3: Loss of Idempotency ---
        deterministic_id = str(uuid.UUID(p['chunk_id'][:32].zfill(32)))
        
        points.append(PointStruct(
            id=deterministic_id,
            vector={
                DENSE_NAME: dense_vec,
                SPARSE_NAME: sparse_vec
            }, 
            payload=p
        ))

    # Upsert to Database
    client.upsert(collection_name=collection_name, points=points)
    print(f"--- SUCCESS: {len(points)} Hybrid points saved to Qdrant ---")