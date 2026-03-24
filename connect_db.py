import os
import chromadb
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

CHROMA_PATH = "./chroma_db_vlm" 
COLLECTION_NAME = "latrobe_policy_v4"

print("Initializing Embedding Model: all-MiniLM-L6-v2...")
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

try:
    chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
    
    db = Chroma(
        client=chroma_client, 
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings
    )
    
    print(f"Successfully connected to {COLLECTION_NAME}")
    
    
    retriever = db.as_retriever(search_kwargs={"k": 5})
    
    query = "How are the ATAR scores adjusted?"
    print(f"\n--- Testing Retrieval for: '{query}' ---")
    
    docs = retriever.invoke(query)
    
    if not docs:
        print("No matching documents found. Ensure the chroma_db_vlm folder is in the correct directory.")
    else:
        
        for i, doc in enumerate(docs):
            
            source_file = doc.metadata.get("source", "Unknown File")
            breadcrumb = doc.metadata.get("breadcrumb", "General Document")
            audience_tag = doc.metadata.get("audience", "Unknown")
            category_tag = doc.metadata.get("category", "Unknown")
            doc_type = doc.metadata.get("doc_type", "Unknown")
            effective_year = doc.metadata.get("effective_year", "Unknown")
            review_year = doc.metadata.get("review_year", "Unknown")
            has_table = doc.metadata.get("has_table", False)
            
            print(f"\n[Result {i+1}]")
            print(f"Source: {source_file}")
            print(f"Section: {breadcrumb}")
            print(f"Audience: {audience_tag} | Category: {category_tag}")
            print(f"Effective Year: {effective_year}")
            
            print(f"Content:\n{doc.page_content}\n")

except Exception as e:
    print(f" Error: {e}")
    print("Troubleshooting: Ensure 'chroma_db_vlm' is in the same folder as this script.")
