import os

# -------------------------------------------------------------------------
# Policy source configuration
# -------------------------------------------------------------------------

# Official public policy directory used to discover policy document links.
WEB_HUB_URL = os.getenv(
    "WEB_HUB_URL",
    "https://policies.latrobe.edu.au/browse",
)

# -------------------------------------------------------------------------
# Database configuration
# -------------------------------------------------------------------------

# Uses the local Qdrant service by default. Environment variables allow the
# application to connect to another Qdrant instance without changing the code.
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")

# Fixed alias used by the retrieval layer. After a candidate collection has
# passed ingestion checks, this alias can be redirected to the new collection.
COLLECTION_ALIAS = os.getenv(
    "QDRANT_COLLECTION_ALIAS",
    "university_policies",
)

# -------------------------------------------------------------------------
# Embedding and reranking model configuration
# -------------------------------------------------------------------------

# Dense embeddings support semantic similarity search.
DENSE_MODEL_NAME = "nomic-embed-text"
DENSE_VECTOR_SIZE = 768
DENSE_VECTOR_NAME = "text-dense"

# Ollama endpoint used to generate dense embeddings during chunking and insertion.
OLLAMA_EMBED_URL = os.getenv(
    "OLLAMA_EMBED_URL",
    "http://localhost:11434/api/embed",
)

# Ollama model and endpoint used to extract experimental audience metadata.
EXTRACTOR_MODEL_NAME = os.getenv(
    "EXTRACTOR_MODEL_NAME",
    "llama3.2",
)
OLLAMA_CHAT_URL = os.getenv(
    "OLLAMA_CHAT_URL",
    "http://localhost:11434/api/chat",
)

# Sparse embeddings support keyword matching for policy terms and document codes.
SPARSE_MODEL_NAME = "prithivida/Splade_PP_en_v1"
SPARSE_VECTOR_NAME = "text-sparse"

# Reranker model used to improve the ordering of retrieved policy chunks.
RERANKER_MODEL_NAME = "BAAI/bge-reranker-base"

# -------------------------------------------------------------------------
# Database and ingestion execution settings
# -------------------------------------------------------------------------

# Maximum number of connection attempts when waiting for Qdrant to become ready.
MAX_DB_RETRIES = 3

# Limit concurrent dense embedding calls so local Ollama requests remain stable.
MAX_DENSE_EMBED_WORKERS = int(
    os.getenv("MAX_DENSE_EMBED_WORKERS", "2")
)

# Retry temporary dense-embedding failures before stopping document insertion.
MAX_EMBED_RETRIES = int(
    os.getenv("MAX_EMBED_RETRIES", "3")
)

# -------------------------------------------------------------------------
# Current role-aware retrieval schema
# -------------------------------------------------------------------------

# Broad user cohorts supported by the active retrieval filter.
VALID_ROLES = {"Student", "Staff", "Public"}
DEFAULT_ROLE = "Public"

# These names must match the metadata keys stored with each validated chunk.
ROLE_FIELD = "target_cohort"
CONTEXTUAL_FIELD = "contextual_audience_tags"
ACCESS_FIELD = "access_level"
EXCEPTION_FIELD = "is_exception"