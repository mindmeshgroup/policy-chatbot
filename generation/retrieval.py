# 1. Initialize the retriever object
from backend.database.connect_db import db
retriever = db.as_retriever(search_kwargs={"k": 5})

def retrieve_policy_chunks(question: str):
    print(f" Searching database for: {question}")
    
    # .invoke() handles the embedding of the question and the search in one go...
    relevant_docs = retriever.invoke(question)
    
    # Validation
    if not relevant_docs:
        print("No relevant policy chunks found.")
        return []

    # Previewing the retrieved data 
    for i, doc in enumerate(relevant_docs):
        source_file = doc.metadata.get("source", "Unknown File")
        breadcrumb=doc.metadata.get("breadcrumb", "General Document")
        print(f"Match {i+1}: {source_file} - {breadcrumb}")
        
    return relevant_docs

# TEST RUN
query = "How are the ATAR scores adjusted?"
chunks = retrieve_policy_chunks(query)
