import asyncio
import json
from qdrant_client import AsyncQdrantClient

client = AsyncQdrantClient(url="http://localhost:6333")
COLLECTION_NAME = "university_policies"

# The Comprehensive Data Contract
REQUIRED_STRUCTURE = {
    "basic": ["document_title", "source_url", "content", "doc_type", "status"],
    "nested": {
        "enquiries_contact": ["name", "email"],
        "responsible_manager": ["name", "email"],
        "department_owner": ["name", "email"]
    },
    "dates": ["effective_date_iso", "review_date"]
}

async def run_integrity_audit():
    print(f" Running Exhaustive Integrity Audit on '{COLLECTION_NAME}'...")
    
    stats = {"total": 0, "issues": []}

    scroll_filter = None
    while True:
        records, next_page = await client.scroll(
            collection_name=COLLECTION_NAME, limit=50, offset=scroll_filter, with_payload=True
        )
        
        for record in records:
            stats["total"] += 1
            payload = record.payload
            
            # 1. Check Basic Fields
            for field in REQUIRED_STRUCTURE["basic"]:
                if not payload.get(field):
                    stats["issues"].append(f"Chunk {record.id}: Missing basic field '{field}'")
            
            # 2. Check Nested Objects
            for field, subfields in REQUIRED_STRUCTURE["nested"].items():
                obj = payload.get(field)
                if not obj or not isinstance(obj, dict):
                    stats["issues"].append(f"Chunk {record.id}: Missing/Invalid object '{field}'")
                else:
                    for sub in subfields:
                        if not obj.get(sub):
                            stats["issues"].append(f"Chunk {record.id}: Missing nested '{field}.{sub}'")

            # 3. Check Dates
            for field in REQUIRED_STRUCTURE["dates"]:
                if not payload.get(field):
                    stats["issues"].append(f"Chunk {record.id}: Missing date '{field}'")

        if next_page is None: break
        scroll_filter = next_page

    # --- FINAL REPORT ---
    print(f"\nAudit Complete. {stats['total']} chunks checked.")
    if stats["issues"]:
        print(f"Found {len(stats['issues'])} issues (showing first 10):")
        for err in stats["issues"][:10]:
            print(f"  - {err}")
    else:
        print("Integrity Check Passed: Full Data Contract Satisfied!")

if __name__ == "__main__":
    asyncio.run(run_integrity_audit())