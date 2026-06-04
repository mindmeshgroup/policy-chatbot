PolicyDB Retrieval Layer Documentation
1. Overview
The retrieval layer provides a  function (retrieve_policies) that connects the backend chatbot to the Qdrant vector database. It uses  a True Hybrid Search architecture, generating both dense (semantic meaning) and sparse (keyword matching) embeddings simultaneously. Results are combined using Reciprocal Rank Fusion (RRF) and filtered via Attribute-Based Access Control (ABAC) to ensure users only receive policies authorised for their specific cohort.
2. Function Interface
Function: retrieve_policies(question: str, role: str = "Student", max_k: int = 3) -> List[Dict]
Inputs
●	question (str, required): The natural language query from the user.
●	role (str, optional): The user's cohort (e.g., "Student", "Staff"). Used to apply a filter against the target_cohort metadata. Defaults to "Student".
●	max_k (int, optional): The maximum number of fused policy chunks to return. Defaults to 3.
Outputs
Returns a List of Dictionaries (List[Dict]). Each dictionary represents a highly relevant policy chunk formatted strictly to the 4-layer Data Contract (Decision, Citation, Validation, Administrative).
3. Data Flow
When the function is called, it executes the following pipeline:
1.	Validation Check: Cleans the query and verifies semantic density (minimum 2 words).
2.	Dual-Track Vectorisation:
○	Dense Track: Pings local Ollama (nomic-embed-text) for 768-d semantic vectors.
○	Sparse Track: Uses local FastEmbed (Splade_PP_en_v1) for lexical keyword arrays.
3.	ABAC Security Filtering: Constructs a Qdrant FieldCondition forcing a match between the user's role and the document's target_cohort array.
4.	Database Query (Prefetch & Fusion): Executes simultaneous dense and sparse searches in Qdrant (with a 0.30 score threshold on the dense search to drop irrelevant results). Merges the two tracks natively using RRF.
5.	Contract Formatting: Strips vector data and maps the remaining payload into the standardized JSON structure for the LLM generation layer.
4. Empty-State Behavior
To prevent the LLM from hallucinating, the retrieval function acts as a strict gatekeeper. It will safely return an empty list ([]) under the following conditions:
●	Insufficient Query: The query is fewer than 2 words (e.g., "Hello").
●	Irrelevant Query: The query fails to meet the 0.30 dense score threshold (e.g., queries about "pizza" or unrelated topics).
●	Unauthorized Access: The query matches a policy, but the policy's target_cohort does not match the user's role (e.g., a Student asking about internal Staff HR procedures).
●	System Failure: If the embedding model or database connection fails.
5. Expected Output Format (Data Contract Example)
When successful, the function returns an array of JSON objects structured exactly like this example:
JSON:
[
  {
    "score": 1.0,
    "content": "[Privacy Policy > Section 6 > Part H]\n1. determine if a privacy breach has or may have occurred...",
    "has_table": false,
    "is_exception": false,
    "document_title": "Privacy Policy",
    "source_url": "https://policies.latrobe.edu.au/document/view.php?id=1",
    "enquiries_contact": "Policy Advisor +61 3 9479 1839",
    "escalation_contact": "Ask La Trobe or Governance and Policy at policy@latrobe.edu.au.",
    "breadcrumb": "Privacy Policy > Section 6 - Procedures > Part H - Privacy Breach Response",
    "document_summary": "Policy regarding Privacy Policy.",
    "doc_type": "Policy",
    "category": ["Academic", "Policy Library"],
    "access_level": "Public",
    "target_cohort": ["Student", "Staff"],
    "campus_scope": ["All Campuses"],
    "document_id": "506ff3946215",
    "approval_body": "Vice-Chancellor",
    "department_owner": "Commercial, Legal and Risk",
    "status": "Current",
    "effective_date_iso": "2023-08-31",
    "review_date": "31st August 2026",
    "chunk_id": "76321893-1854-4fd7-94bd-4eb38a356c47",
    "chunk_index": 114,
    "chunk_type": "Text"
  }
]
7. Technology Stack & Architectural Rationale
The retrieval and ingestion layers were built using a carefully selected stack designed to prioritize data privacy, asynchronous speed, and high-precision search.
Ingestion and Scraping Layer
•	Crawl4AI & Asyncio.
o	Traditional scrapers often fail on modern university websites. Crawl4AI, paired with Python's asyncio, allowed us to execute JavaScript (WAIT_JS) and asynchronously map the entire Policy Hub. This ensures we capture all dynamically loaded internal links without timing out.
•	BeautifulSoup 4 & Hashlib
o	BS4 allows us to surgically extract the "Status and Details" table from a separate URL and inject it into the main document's DOM before processing. Hashlib generates MD5 hashes of the raw text, creating an idempotent update checker that skips unchanged pages and saves massive amounts of compute time.
•	Docling (Hierarchical Chunker)
o	Traditional text splitters blindly slice sentences in half and destroy tables. Docling understands the visual hierarchy of the policy, keeping tables intact and generating sequential "breadcrumbs" (e.g., Privacy Policy > Section 6 > Part H) so the chatbot always knows the exact context of a chunk.
Processing & AI Layer
•	Llama3 (via Local Ollama)
o	Used in metadata_factory.py for Intelligent Information Extraction. Instead of relying on brittle Regex, we feed the "Scope" section of the policy to Llama3 to accurately classify the target_cohort (Staff vs. Student) and extract governance dates.
•	nomic-embed-text (via Local Ollama)
o	Generates the Dense Vectors (semantic meaning). 
•	FastEmbed (Splade_PP_en_v1).
o	Generates the Sparse Vectors (keyword matching). While dense vectors understand "meaning", they often fail at exact keyword matches (like specific Policy IDs or acronyms like "CGRIASC"). SPLADE acts as our lexical search engine, ensuring exact text matches are never missed.
Storage & Retrieval Layer
•	Qdrant (Local Docker Container)
o	Running Qdrant via Docker guarantees strict data privacy (no cloud exposure). Moreover,, Qdrant natively supports True Hybrid Search (managing both dense and sparse vectors simultaneously) and Payload Indexing, which allows for lightning-fast ABAC security filtering.
•	Reciprocal Rank Fusion (RRF)
o	Semantic distance scores and keyword match scores use completely different mathematical scales. RRF ignores the raw scores and fuses the results based on their rankings (1st place, 2nd place), providing a mathematically sound "best of both worlds" search result.


