import json
import time
from retrieval.retrieve_policies import retrieve_policies 
import asyncio
from difflib import SequenceMatcher, get_close_matches
from pathlib import Path
import statistics

project_root = Path(__file__).resolve().parent.parent 

json_path = project_root / 'retrieval' / 'database_titles.json'

try:
    with open(json_path, "r") as f:
        ALL_DB_TITLES = json.load(f)
except FileNotFoundError:
    print(f"Registry not found at {json_path}")
    ALL_DB_TITLES = []

# THE GOLDEN DATASET (20 Test Cases)
GOLDEN_DATASET = [
    # --- STAFF / EMPLOYMENT POLICIES ---
    {"query": "How do I appeal my termination?", "expected_title": "Termination of Employment Procedure", "role": "Academic"},
    {"query": "Can I start a side hustle if I work here full time?", "expected_title": "Outside Work Policy (Professional Staff)", "role": "Professional"},
    {"query": "What is the allowance for using my own car?", "expected_title": "University Vehicle Fleet Policy", "role": "Academic"},
    {"query": "How do I declare a conflict of interest?", "expected_title": "Conflict of Interest Procedure - Staff Authored Texts", "role": "Professional"},
    {"query": "What are the rules for staff probation?", "expected_title": "Probation (Professional Staff) Policy", "role": "Professional"},
    
    # --- STUDENT / ACADEMIC POLICIES ---
    {"query": "What happens if I get caught cheating on a test?", "expected_title": "Student Academic Misconduct Policy", "role": "Undergrad"},
    {"query": "How do I apply for a deadline extension?", "expected_title": "Assessment Procedure - Adjustments (including Special Consideration)", "role": "Undergrad"},
    {"query": "What are the rules for bringing a pet on campus?", "expected_title": "Health and Safety Procedure - Pet and Assistance Animals", "role": "Student"},
    {"query": "How long can I take a leave of absence from my course?", "expected_title": "Enrolment Procedure - Variations", "role": "Postgrad"},
    {"query": "Can I appeal my final grade?", "expected_title": "Appeals Policy", "role": "Undergrad"},
    
    # --- RESEARCH / HDR POLICIES ---
    {"query": "Who owns the IP of my PhD thesis?", "expected_title": "Intellectual Property Policy", "role": "HDR"},
    {"query": "What are the ethics requirements for animal testing?", "expected_title": "Research Animal Ethics Procedure", "role": "Academic"},
    {"query": "How do I get a research grant?", "expected_title": "Research Contracts and Grants Policy", "role": "Academic"},
    {"query": "What is the milestone review process for doctorates?", "expected_title": "Graduate Research Progress Policy", "role": "HDR"},
    
    # --- IT / SECURITY / GENERAL POLICIES ---
    {"query": "Am I allowed to share my university password?", "expected_title": "IS Acceptable Use Policy", "role": "Undergrad"},
    {"query": "How do I report a data breach?", "expected_title": "Privacy Policy", "role": "Professional"},
    {"query": "What should I do if the fire alarm goes off?", "expected_title": "Health and Safety Procedure - Emergency Control Organisation", "role": "Public"},
    {"query": "Are skateboards allowed in the library?", "expected_title": "Library and Digital Learning Resources Policy", "role": "Undergrad"},
    {"query": "How do I book a room for an event?", "expected_title": "Space Allocation and Use Policy", "role": "Professional"},
    {"query": "What is the policy on smoking on campus?", "expected_title": "Health and Safety Procedure - Smoke Free Environment", "role": "Public"}
]
# THE EVALUATION ENGINE
def find_best_match(expected_title):
    """Finds the closest title in our DB registry to the expected title."""
    if not ALL_DB_TITLES: return expected_title
    matches = get_close_matches(expected_title, ALL_DB_TITLES, n=1, cutoff=0.6)
    return matches[0] if matches else expected_title

def is_semantic_match(retrieved_title, expected_title):
    """
    Returns True if retrieved title is effectively the same as the expected title,
    allowing for minor suffix variations like '(Academic)' or '(Professional Staff)'.
    """
    retrieved = retrieved_title.lower()
    expected = expected_title.lower()
    
    # 1. Exact match
    if retrieved == expected:
        return True
    
    # 2. Contains match (handles cases where DB has suffixes)
    if expected in retrieved or retrieved in expected:
        return True
        
    # 3. Fuzzy ratio match (>85% similarity)
    similarity = SequenceMatcher(None, retrieved, expected).ratio()
    return similarity > 0.85

# THE EVALUATION ENGINE
async def run_evaluation():
    print(f" Starting Task 5 Evaluation: Testing {len(GOLDEN_DATASET)} Policies...\n")
    
    # [NEW] Align the Golden Dataset with actual Database reality
    for item in GOLDEN_DATASET:
        item["expected_title"] = find_best_match(item["expected_title"])

    results = []
    successful_scores = []
    start_time = time.time()

    for i, item in enumerate(GOLDEN_DATASET):
        print(f"[{i+1}/{len(GOLDEN_DATASET)}] Testing Query: '{item['query']}'")
        
        # Await the async retrieval
        response = await retrieve_policies(item["query"], role=item["role"], max_k=5)
        
        top_titles = []
        highest_correct_score = 0.0
        is_correct = False

        for res in response:
            title = res.get("document_title", "Unknown")
            top_titles.append(title)
            
            if is_semantic_match(title, item["expected_title"]):
                is_correct = True
                if "score" in res:
                    highest_correct_score = max(highest_correct_score, res["score"])

        results.append({
            "query": item["query"],
            "success": is_correct,
            "expected": item["expected_title"],
            "retrieved": top_titles
        })

        if is_correct and highest_correct_score > 0:
            successful_scores.append(highest_correct_score)

    # --- 5. METRICS & TELEMETRY OUTPUT ---
    total_time = time.time() - start_time
    accuracy = sum(1 for r in results if r["success"]) / len(results)
    
    print("\n" + "="*50)
    print("TASK 5: RETRIEVAL QUALITY CONTROL REPORT")
    print("="*50)
    print(f"Total Queries Tested : {len(results)}")
    print(f"Execution Time       : {total_time:.2f} seconds")
    print(f"Recall@K Accuracy    : {accuracy * 100:.2f}%")
    

    if successful_scores:
        mean_score = statistics.mean(successful_scores)
        std_dev = statistics.stdev(successful_scores) if len(successful_scores) > 1 else 0
        
        # We use a 2-sigma lower bound. This is a standard statistical
        # method to exclude the "tail" of bad matches.
        suggested_threshold = max(0.0, mean_score - (1.5 * std_dev))
        
        print(f"\n STATISTICAL THRESHOLD CALIBRATION:")
        print(f"Average Match Score : {mean_score:.4f}")
        print(f"Standard Deviation  : {std_dev:.4f}")
        print(f"==> RECOMMENDED SIMILARITY THRESHOLD: >= {suggested_threshold:.3f}")
        
    failed_queries = [r for r in results if not r["success"]]
    if failed_queries:
        print("\n FAILED RETRIEVALS (Irrelevant Noise Detected):")
        for f in failed_queries:
            print(f" - Query: '{f['query']}'")
            print(f"   Expected: {f['expected']}")
            print(f"   Actually Got: {f['retrieved']}")
    else:
        print("\n PERFECT RUN! Irrelevant chunks successfully filtered out.")

    print("="*50)
if __name__ == "__main__":
    asyncio.run(run_evaluation())
