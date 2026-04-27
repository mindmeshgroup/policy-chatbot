import json
import ollama
from typing import List, Dict
from qdrant_client import QdrantClient
from qdrant_client import models
from fastembed import SparseTextEmbedding

# --- CONFIGURATION ---
# Connects to your Docker container
client = QdrantClient(url="http://localhost:6333")
COLLECTION_NAME = "university_policies"

# Initialize Models
DENSE_MODEL = "nomic-embed-text"

# Initialize the Sparse Embedding Model (SPLADE) for retrieval
print("Loading Sparse Embedding Model (SPLADE)...")
sparse_model = SparseTextEmbedding(model_name="prithivida/Splade_PP_en_v1")

def retrieve_policies(question: str, role: str = "Student", max_k: int = 3) -> List[Dict]:
    """
    Executes a True Hybrid Search (Dense + Sparse) with Reciprocal Rank Fusion (RRF).
    Returns a strict JSON data contract.
    """
    # 1. PRE-RETRIEVAL VALIDATION
    cleaned_query = question.strip()
    if len(cleaned_query.split()) < 2:
        print(f"[REJECTED] Query '{cleaned_query}' lacks sufficient semantic density.")
        return []

    # 2. VECTOR GENERATION (Dual-Track)
    try:
        # A. Dense Vector (Meaning/Context) via Ollama
        dense_response = ollama.embeddings(model=DENSE_MODEL, prompt=cleaned_query)
        dense_vector = dense_response['embedding']
        
        # B. Sparse Vector (Exact Keyword/Acronym Matching) via FastEmbed
        sparse_generator = list(sparse_model.embed([cleaned_query]))
        sparse_result = sparse_generator[0]
        
        sparse_vector_obj = models.SparseVector(
            indices=sparse_result.indices.tolist(),
            values=sparse_result.values.tolist()
        )
    except Exception as e:
        print(f"[ERROR] Embedding generation failed: {e}")
        return []

    # 3. METADATA FILTERING (ABAC)
    query_filter = None
    if role:
        query_filter = models.Filter(
            must=[models.FieldCondition(key="target_cohort", match=models.MatchValue(value=role))]
        )

    # 4. HYBRID DATABASE SEARCH (RRF FUSION)
   # 4. HYBRID DATABASE SEARCH (RRF FUSION)
    try:
        results = client.query_points(
            collection_name=COLLECTION_NAME,
            prefetch=[
                # Track 1: Semantic Dense Search (Now Quantization-Aware)
                models.Prefetch(
                    query=dense_vector,
                    using="text-dense",
                    filter=query_filter,
                    limit=max_k * 2,
                    score_threshold=0.30, # removes irrelevant queries before fusion
                    # Rescoring and oversampling to maintain accuracy with INT8 compression
                    params=models.SearchParams(
                        quantization=models.QuantizationSearchParams(
                            ignore=False,
                            rescore=True,
                            oversampling=3.0
                        )
                    )
                ),
                # Track 2: Lexical Sparse Search (Unchanged)
                models.Prefetch(
                    query=sparse_vector_obj,
                    using="text-sparse",
                    filter=query_filter,
                    limit=max_k * 2
                )
            ],
            # Combine the two tracks using Reciprocal Rank Fusion
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=max_k
        )
    except Exception as e:
        print(f"[ERROR] Database query failed: {e}")
        return []

    # 5. DATA CONTRACT ENFORCEMENT
    formatted_results = []
    
    for point in results.points:
        payload = point.payload
        contract_item = {
            # --- LAYER 1: DECISION GROUP ---
            "score": round(point.score, 4),
            "content": payload.get("content", ""),
            "has_table": payload.get("has_table", False),
            "is_exception": payload.get("is_exception", False),

            # --- LAYER 2: CITATION GROUP ---
            "document_title": payload.get("document_title", "Unknown Document"),
            "source_url": payload.get("source_url", ""),
            "enquiries_contact": payload.get("enquiries_contact", "University Administration"),
            "escalation_contact": payload.get("escalation_contact", "Ask La Trobe"),
            "breadcrumb": payload.get("breadcrumb", ""),
            "document_summary": payload.get("document_summary", ""),

            # --- LAYER 3: VALIDATION GROUP ---
            "doc_type": payload.get("doc_type", "Policy"),
            "category": payload.get("category", []),
            "access_level": payload.get("access_level", "Public"),
            "target_cohort": payload.get("target_cohort", ["Student", "Staff"]),
            "campus_scope": payload.get("campus_scope", ["All Campuses"]),

            # --- LAYER 4: ADMINISTRATIVE GROUP ---
            "document_id": payload.get("document_id", ""),
            "approval_body": payload.get("approval_body", ""),
            "department_owner": payload.get("department_owner", ""),
            "status": payload.get("status", "Current"),
            "effective_date_iso": payload.get("effective_date_iso", None),
            "review_date": payload.get("review_date", None),
            "chunk_id": payload.get("chunk_id", ""),
            "chunk_index": payload.get("chunk_index", 0),
            "chunk_type": payload.get("chunk_type", "Text")
        }
        
        formatted_results.append(contract_item)

    return formatted_results

def run_validation_test(query: str, role: str):
    print(f"\n" + "═"*60)
    print(f"RUNNING VALIDATION FOR: '{query}'")
    print(f"ROLE: {role}")
    print("═"*60)
    
    raw_json = retrieve_policies(query, role=role)
    print(json.dumps(raw_json, indent=2))

if __name__ == "__main__":
    print("========================================")
    print("  LA TROBE POLICYDB - HYBRID TEST SUITE  ")
    print("========================================\n")

    # TEST 1: Privacy Policy
    run_validation_test("How quickly must I report a privacy data breach?", role="Student")

    # TEST 2: IP Ownership
    run_validation_test("Do students own the IP they create?", role="Student")

    # TEST 3: Outside Work Policy
    run_validation_test("What is the maximum number of days for paid personal work?", role="Staff")

    # TEST 4: Security Filter Test
    run_validation_test("How do I get approval for University Consulting?", role="Student")

    # TEST 5: Metadata Enquiry Validation
    run_validation_test("Who is the enquiries contact for Outside Work?", role="Staff")

    # TEST 6: Irrelevant Query (Pizza Test)
    run_validation_test("Where can I find a good pepperoni pizza?", role="Student")

    # TEST 7: Semantic Density Check
    run_validation_test("Hello", role="Student")