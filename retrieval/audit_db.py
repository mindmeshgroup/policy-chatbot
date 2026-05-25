from qdrant_client import QdrantClient
import os
# Update this to match your collection name
COLLECTION_NAME = "university_policies"

def audit_titles():
    client = QdrantClient(url="http://localhost:6333")
    unique_titles = set()
    
    print(f" Auditing database for unique titles in '{COLLECTION_NAME}'...")
    
    # Use scroll to efficiently paginate through the collection
    last_id = None
    while True:
        records, next_page = client.scroll(
            collection_name=COLLECTION_NAME,
            limit=100,
            offset=last_id,
            with_payload=["document_title"]
        )
        
        for record in records:
            if "document_title" in record.payload:
                unique_titles.add(record.payload["document_title"])
        
        if next_page is None:
            break
        last_id = next_page

    # Sort and Print
    sorted_titles = sorted(list(unique_titles))
    print(f"\nFound {len(sorted_titles)} unique document titles:\n")
    for title in sorted_titles:
        print(f" - {title}")
        
    # Save to a JSON file for your test script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 3. Save the file into that directory (or the parent if it's in utils)
    # If the script is in 'retrieval/utils', this places it in 'retrieval/'
    save_path = os.path.join(script_dir, 'database_titles.json')
    
    with open(save_path, "w") as f:
        json.dump(sorted_titles, f, indent=2)
    
    print(f"\n Saved titles to: {os.path.abspath(save_path)}")
if __name__ == "__main__":
    import json
    audit_titles()