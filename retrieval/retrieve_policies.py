import json
import ollama
import math
from ollama import AsyncClient # Add this to imports
import asyncio
from typing import List, Dict
from qdrant_client import AsyncQdrantClient
from qdrant_client import models
from fastembed import SparseTextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder
from retrieval.utils.query_rewriter import rewrite_query
# --- CONFIGURATION ---
# IMPORTANT: Switched to AsyncQdrantClient for parallel CRAG queries
client = AsyncQdrantClient(url="http://localhost:6333")
COLLECTION_NAME = "university_policies"

# Initialize Models
DENSE_MODEL = "nomic-embed-text"

print("Loading Sparse Embedding Model (SPLADE)...")
sparse_model = SparseTextEmbedding(model_name="prithivida/Splade_PP_en_v1")

print("Loading Cross-Encoder Reranking Model...")
reranker = TextCrossEncoder(model_name="BAAI/bge-reranker-base")
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

async def fetch_standard_track(dense_vector, sparse_vector_obj, rbac_filter):
    """Executes the Standard Hybrid RRF Search."""
    return await client.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=[
            models.Prefetch(
                query=dense_vector,
                using="text-dense",
                filter=rbac_filter,
                limit=40,
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
                limit=40
            )
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=20
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
                score_threshold=0.20, # <--- Add a safety net here
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
    Now fully asynchronous with parallel CRAG execution and Semantic Rewriting.
    """
    # 1. PRE-RETRIEVAL VALIDATION & REWRITING
    VALID_ROLES = {"Student", "Academic", "Professional", "Casual", "Public", "Guest"}
    if role not in VALID_ROLES:
        print(f"[SECURITY WARNING] Invalid role '{role}' detected. Demoting to Public.")
        role = "Public"
        
    cleaned_query = question.strip()
    if len(cleaned_query.split()) < 2:
        print(f"[REJECTED] Query '{cleaned_query}' lacks sufficient semantic density.")
        return []

    print(f"\n[RETRIEVAL] Raw User Query: '{cleaned_query}'")
    
    # --- NEW: THE ASYNC REWRITER INTERCEPT ---
    rewritten = await rewrite_query(cleaned_query, role)
    
    print(f"  [REWRITER] Cleaned:   {rewritten['cleaned_query']}")
    print(f"  [REWRITER] Technical: {rewritten['technical_query']}")
    print(f"  [REWRITER] Step-Back: {rewritten['step_back_query']}")
    
    # Combine variants for maximum dense vector meaning
    optimized_semantic_query = f"{rewritten['technical_query']} {rewritten['step_back_query']}"
    # Use cleaned variant for exact sparse keyword hits
    optimized_keyword_query = rewritten['cleaned_query']

    # 2. ASYNC VECTOR GENERATION (Using optimized queries)
    try:
        ollama_client = AsyncClient()
        # Fetch the Dense embedding using the complex, technical query
        dense_response = await ollama_client.embeddings(model=DENSE_MODEL, prompt=optimized_semantic_query)
        dense_vector = dense_response['embedding']
        
        # Offload CPU-heavy Sparse embedding to a background thread using the exact keyword query
        sparse_generator = await asyncio.to_thread(lambda: list(sparse_model.embed([optimized_keyword_query])))
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
        standard_task = fetch_standard_track(dense_vector, sparse_vector_obj, rbac_filter)
        exception_task = fetch_exception_track(dense_vector, sparse_vector_obj, rbac_filter)
        
        # Await them together (Zero Latency Overhead)
        standard_results, exception_results = await asyncio.gather(standard_task, exception_task)
        
    except Exception as e:
        print(f"[ERROR] Database query failed: {e}")
        return []

    # 5. CONTEXT BUNDLING & DEDUPLICATION
    standard_chunks = []
    exception_chunks = []
    seen_ids = set()

    all_points = list(standard_results.points) + list(exception_results.points)

    for point in all_points:
        chunk_id = point.payload.get("chunk_id")
        if chunk_id not in seen_ids:
            seen_ids.add(chunk_id)
            if point.payload.get("is_exception") == True:
                exception_chunks.append(point)
            else:
                standard_chunks.append(point)

    # ==========================================
    # TASK 2: CROSS-ENCODER RERANKING INTERCEPT
    # ==========================================
   # ==========================================
    # TASK 2: CROSS-ENCODER RERANKING INTERCEPT
    # ==========================================
    if all_points:
        print(f"  [RERANKER] Deep evaluating {len(all_points)} total chunks...")
        documents = [point.payload.get("content", "") for point in all_points]
        
        # Grade EVERYTHING
        scores = await asyncio.to_thread(
            lambda: list(reranker.rerank(cleaned_query, documents))
        )
        
        reranked_points = []
        for point, raw_logit in zip(all_points, scores):
            safe_logit = max(min(float(raw_logit), 100), -100)
            probability_score = 1 / (1 + math.exp(-safe_logit))
            point.score = probability_score # Overwrite all scores
            reranked_points.append(point)
        
        # Sort everything by true probability
        reranked_points.sort(key=lambda x: x.score, reverse=True)
        
        # Now, separate the top standard chunks and the top exceptions safely
        standard_chunks = []
        exception_chunks = []
        
        for point in reranked_points:
            if point.payload.get("is_exception") == True:
                if len(exception_chunks) < 2: # Keep max 2 exceptions
                    exception_chunks.append(point)
            else:
                if len(standard_chunks) < max_k: # Keep max_k standard chunks
                    standard_chunks.append(point)

    final_points = standard_chunks + exception_chunks
    # ==========================================

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

async def run_all_tests():
   
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
    # test_queries = [
    #     # --- 1. THE "MESSY / SLANG" TESTS (Testing Cleaned & Technical Translation) ---
    #     # Tests if Qwen can fix the typos and translate "fired" into "Termination of Employment"
    #     ("i got fired and want to apeal my termnation, how do i do that?", "Professional"),
        
    #     # Tests if Qwen translates "side hustle/gig" into "Outside Work" and "Consulting"
    #     ("can i start a side hustle or freelance gig if I work here full time?", "Academic"),
        
    #     # --- 2. THE "VAGUE / ABSTRACT" TESTS (Testing the Step-Back Prompt) ---
    #     # Tests if Qwen abstracts "throwing away old emails" to "Records Management Data Retention"
    #     ("what are the rules for throwing away old student emails?", "Professional"),
        
    #     # Tests if Qwen understands that "inventing a new app" falls under "Intellectual Property Policy"
    #     ("if I build a new app in my dorm room, does the university own it?", "Student"),

    #     # --- 3. THE "IMPLICIT FILTER" TESTS (Testing ABAC Metadata Extraction) ---
    #     # Tests if Qwen correctly extracts the ["Academic", "HDR"] implicit filter from the text
    #     ("I'm a lead researcher, what are the safety rules for bringing hazardous chemicals into the lab?", "Academic"),
        
    #     # Tests if Qwen extracts ["Student"] and maps "thesis paper" to "Research Authorship"
    #     ("as a phd student, who gets to be the first author on my thesis paper?", "Student"),

    #     # --- 4. THE "MULTI-HOP / COMPLEX" TESTS (Testing Concept Fusion) ---
    #     # Tests if Qwen can merge Concepts: Grants + Data Management + Privacy
    #     ("If I get a government grant, how long do I have to keep the sensitive patient data before deleting it?", "Academic"),
        
    #     # Tests if Qwen identifies "Research Integrity" vs standard "Termination"
    #     ("what happens if an academic gets caught falsifying their grant data?", "Professional")
    # ]

    all_results = {}
    for query, role in test_queries:
        print(f"\n" + "═"*60)
        print(f"Running Validation For: '{query}' (Role: {role})")
        print("═"*60)
        
        # Await safely inside a single event loop
        res = await retrieve_policies(query, role=role)
        all_results[query] = res

    with open("test_results.json", "w") as f:
        json.dump(all_results, f, indent=2)
        
    print("\n All tests complete! Open 'test_results.json' to see the full output.")

if __name__ == "__main__":
    # Start the event loop ONCE for the entire script
    asyncio.run(run_all_tests())