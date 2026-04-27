import json
import ollama
import asyncio
from typing import List, Dict
from qdrant_client import AsyncQdrantClient
from qdrant_client import models
from fastembed import SparseTextEmbedding

# --- CONFIGURATION ---
# IMPORTANT: Switched to AsyncQdrantClient for parallel CRAG queries
client = AsyncQdrantClient(url="http://localhost:6333")
COLLECTION_NAME = "university_policies"

# Initialize Models
DENSE_MODEL = "nomic-embed-text"

print("Loading Sparse Embedding Model (SPLADE)...")
sparse_model = SparseTextEmbedding(model_name="prithivida/Splade_PP_en_v1")


def get_rbac_filter(role: str) -> models.Filter:
    """
    Generates the true ABAC/RBAC MatchAny filter.
    Always grants access to Public and Guest documents.
    """
    allowed_roles = [role, "Public", "Guest"] if role else ["Public", "Guest"]
    return models.Filter(
        must=[
            models.FieldCondition(
                key="target_cohort",
                match=models.MatchAny(any=allowed_roles) # Upgraded to MatchAny
            )
        ]
    )

async def fetch_standard_track(dense_vector, sparse_vector_obj, rbac_filter, max_k):
    """Executes the Standard Hybrid RRF Search."""
    return await client.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=[
            models.Prefetch(
                query=dense_vector,
                using="text-dense",
                filter=rbac_filter,
                limit=max_k * 2,
                score_threshold=0.30, # Keeps out low-relevance standard docs
                params=models.SearchParams(
                    quantization=models.QuantizationSearchParams(
                        ignore=False, rescore=True, oversampling=3.0
                    )
                )
            ),
            models.Prefetch(
                query=sparse_vector_obj,
                using="text-sparse",
                filter=rbac_filter,
                limit=max_k * 2
            )
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=max_k
    )

async def fetch_exception_track(dense_vector, sparse_vector_obj, rbac_filter):
    """Executes the Exception-Targeted Hybrid RRF Search."""
    # Create the Hard Pre-Filter for Exceptions
    exception_filter = models.Filter(
        must=rbac_filter.must + [
            models.FieldCondition(
                key="is_exception", 
                match=models.MatchValue(value=True)
            )
        ]
    )

    return await client.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=[
            models.Prefetch(
                query=dense_vector,
                using="text-dense",
                filter=exception_filter,
                limit=2,
                # NO score_threshold: We "Always-Fetch" overrides even if semantic match is lower
                params=models.SearchParams(
                    quantization=models.QuantizationSearchParams(
                        ignore=False, rescore=True, oversampling=3.0
                    )
                )
            ),
            models.Prefetch(
                query=sparse_vector_obj,
                using="text-sparse",
                filter=exception_filter,
                limit=2
            )
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=2
    )

async def retrieve_policies(question: str, role: str = "Student", max_k: int = 3) -> List[Dict]:
    """
    Executes a True Hybrid Search (Dense + Sparse) with Reciprocal Rank Fusion (RRF).
    Now fully asynchronous with parallel CRAG execution.
    """
    # 1. PRE-RETRIEVAL VALIDATION
    cleaned_query = question.strip()
    if len(cleaned_query.split()) < 2:
        print(f"[REJECTED] Query '{cleaned_query}' lacks sufficient semantic density.")
        return []

    # 2. VECTOR GENERATION (Synchronous blocking, but safe for single queries)
    try:
        dense_response = ollama.embeddings(model=DENSE_MODEL, prompt=cleaned_query)
        dense_vector = dense_response['embedding']
        
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
    rbac_filter = get_rbac_filter(role)

    # 4. ASYNCHRONOUS PARALLEL HYBRID SEARCH (CRAG)
    try:
        # Fire both Hybrid RRF queries at Qdrant simultaneously
        standard_task = fetch_standard_track(dense_vector, sparse_vector_obj, rbac_filter, max_k)
        exception_task = fetch_exception_track(dense_vector, sparse_vector_obj, rbac_filter)
        
        # Await them together (Zero Latency Overhead)
        standard_results, exception_results = await asyncio.gather(standard_task, exception_task)
        
    except Exception as e:
        print(f"[ERROR] Database query failed: {e}")
        return []

    # 5. CONTEXT BUNDLING & DEDUPLICATION
    final_points = []
    seen_ids = set()

    for point in standard_results.points:
        final_points.append(point)
        seen_ids.add(point.payload.get("chunk_id"))

    for exp_point in exception_results.points:
        chunk_id = exp_point.payload.get("chunk_id")
        if chunk_id not in seen_ids:
            # Append exceptions to the very bottom to exploit LLM Recency Bias
            final_points.append(exp_point)
            seen_ids.add(chunk_id)

    # 6. DATA CONTRACT ENFORCEMENT
    formatted_results = []
    
    for point in final_points:
        payload = point.payload
        contract_item = {
            # --- LAYER 1: DECISION GROUP ---
            "score": round(point.score, 4) if getattr(point, 'score', None) is not None else 0.0,
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
    
    # Notice the asyncio.run() because retrieve_policies is now an async function
    raw_json = asyncio.run(retrieve_policies(query, role=role))
    print(json.dumps(raw_json, indent=2))

if __name__ == "__main__":
   
    print("  LA TROBE POLICYDB - HYBRID TEST SUITE  ")
    
    test_queries = [
        ("How quickly must I report a privacy data breach?", "Student"),
        ("Do students own the IP they create?", "Student"),
        ("What is the maximum number of days for paid personal work?", "Academic"),
        ("How do I get approval for University Consulting?", "Student"),
        ("Who is the enquiries contact for Outside Work?", "Professional"),
        ("Where can I find a good pepperoni pizza?", "Student"),
        ("Will the University pay for my patent protection beyond the provisional stage?", "Academic"),
        ("Can La Trobe sign an industry contract that delays the publication of my research?", "Academic"),
        ("Can I freely publish teaching materials that I co-authored on the internet?", "Academic"),
        ("Are all active business records freely accessible to everyone across the University?", "Professional"),
        ("If my expired records have been authorised for destruction, are there any situations where I still cannot destroy them?", "Professional"),
        ("If my co-author and I are arguing over the order of our names on a paper, is that considered research misconduct?", "Academic"),
        ("Hello", "Student")
    ]

    all_results = {}
    for query, role in test_queries:
        print(f"Running Validation For: '{query}' (Role: {role})")
        # Ensure we capture the empty list if a query is rejected
        res = asyncio.run(retrieve_policies(query, role=role))
        all_results[query] = res

    # Write the entire output to a JSON file so you can inspect it in VS Code
    with open("test_results.json", "w") as f:
        json.dump(all_results, f, indent=2)
        
    print("\n All tests complete! Open 'test_results.json' to see the full output.")