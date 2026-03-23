import os
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

# 1. Define the path to the folder you downloaded from OneDrive
CHROMA_PATH = "chroma_db" 

# 2. Set up the EXACT same embedding model Veidehi used
# This will download a small model (about 80MB) the first time you run it
model_name = "sentence-transformers/all-MiniLM-L6-v2"
model_kwargs = {'device': 'cpu'}
encode_kwargs = {'normalize_embeddings': False}

embeddings = HuggingFaceEmbeddings(
    model_name=model_name,
    model_kwargs=model_kwargs,
    encode_kwargs=encode_kwargs
)

# 3. Connect to the existing database
try:
    db = Chroma(
        persist_directory=CHROMA_PATH, 
        embedding_function=embeddings
    )
    print("Successfully connected to the Policy Database using HuggingFace!")

    # 4. TEST: Search the Policy DB
    query = "What is the policy on academic integrity?"
    # Search for the top 3 most relevant parts of the policy
    docs = db.similarity_search(query, k=3)

    print(f"\n--- Search Results for: '{query}' ---")
    for i, doc in enumerate(docs):
        print(f"\nResult {i+1}:")
        print(doc.page_content[:300] + "...") # Print first 300 characters
        
except Exception as e:
    print(f" Error: {e}")