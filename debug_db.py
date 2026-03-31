import os
import chromadb

CHROMA_PATH = "./chroma_db_vlm"

print(f"--- Diagnostic Report ---")
if os.path.exists(CHROMA_PATH):
    files = os.listdir(CHROMA_PATH)
    print(f"Folder exists at: {CHROMA_PATH}")
    print(f"Files found: {files}")
    
    # Check for the actual data folder
    if 'index' in files:
        index_files = os.listdir(os.path.join(CHROMA_PATH, 'index'))
        print(f"Index folder contains {len(index_files)} data files.")
    else:
        print("CRITICAL: 'index' folder is missing. The databse is empty.")
else:
    print(f"Folder NOT found at {CHROMA_PATH}")


try:
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collections = client.list_collections()
    print(f"Collections found in this folder: {[c.name for c in collections]}")
except Exception as e:
    print(f"Error reading collections: {e}")