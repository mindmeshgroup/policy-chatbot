import os
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

CHROMA_PATH = "./chroma_db_vlm" 
COLLECTION_NAME = "latrobe_policy_v4"

# STEP 1 & 2: EMBEDDINGS & CONNECTION
print("Initializing Embedding Model: all-MiniLM-L6-v2...")
model_name = "sentence-transformers/all-MiniLM-L6-v2"
embeddings = HuggingFaceEmbeddings(model_name=model_name)

try:
    # Connecting to the persisted database
    db = Chroma(
        persist_directory=CHROMA_PATH, 
        embedding_function=embeddings,
        collection_name=COLLECTION_NAME
    )
    
    # Verify the connection by checking the chunk count
    chunk_count = db._collection.count()
    print(f" Successfully connected to {COLLECTION_NAME}")
    print(f" Total policy chunks available: {chunk_count}")

    #STEP 3: RETRIEVAL STEP
    
    retriever = db.as_retriever(search_kwargs={"k": 5})

    # Test Query 
    query = "How are the ATAR scores adjusted?"
    print(f"\n--- Testing Retrieval for: '{query}' ---")
    
    # Fetching the documents
    docs = retriever.invoke(query)

    if not docs:
        print(" No matching documents found. Ensure the chroma_db_vlm folder is in the correct directory.")
    else:
        # --- STEP 7: SOURCE METADATA PREVIEW ---
        for i, doc in enumerate(docs):
           
            source_file = doc.metadata.get("source", "Unknown File")
            breadcrumb = doc.metadata.get("breadcrumb", "General Document")
            audience_tag = doc.metadata.get("audience", "Unknown")
            category_tag = doc.metadata.get("category", "Unknown")
            doc_type=doc.metadata.get("doc_type", "Unknown")
            effective_yr=doc.metadata.get("effective_yr", "Unknown")
            review_yr=doc.metadata.get("review_year", "Unknown")
            has_table=doc.metadata.get("has_table", False)
            
            print(f"\n[Result {i+1}]")
            print(f"Source: { source_file}")
            print(f"Section: {breadcrumb}")
            print(f"Target Audience: {audience_tag} | Category: {category_tag}")
            print(f"Content: {doc.page_content[:200]}...")

except Exception as e:
    print(f" Error: {e}")
    print("Troubleshooting: Ensure 'chroma_db_vlm' is in the same folder as this script.")