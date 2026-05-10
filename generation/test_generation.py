"""
Sprint 2 — Task 5: Test Generation Output Consistency

ARCHITECTURE FIX:
  Tests now call generate_answer(question, chunks) with Vaidehi's dict
  chunk format, not a standalone Chroma/LangChain RAG pipeline.

  This validates:
    1. Correct output structure (answer, used_sources)
    2. Correct fallback behaviour when chunks are empty
    3. Determinism (same answer across repeated calls at temperature=0)
"""

import os
from dotenv import load_dotenv

from chatbot import generate_answer
from prompt_logic_v3 import PROMPT_VERSION

load_dotenv()

# ── Shared sample chunks (Vaidehi's dict format) ────────────────────────────────

ACADEMIC_INTEGRITY_CHUNKS = [
    {
        "chunk_id": "ai_001",
        "document_title": "Academic Integrity Policy",
        "source_url": "https://policies.latrobe.edu.au/document/view/academic-integrity-policy",
        "content": (
            "La Trobe University is committed to academic integrity. "
            "Students must not engage in plagiarism, contract cheating, "
            "collusion, fabrication of data, or any other form of academic misconduct."
        ),
        "is_exception": False,
    },
]

ATAR_CHUNKS = [
    {
        "chunk_id": "adm_001",
        "document_title": "Admissions Policy",
        "source_url": "https://policies.latrobe.edu.au/document/view/admissions-policy",
        "content": (
            "ATAR scores may be adjusted through the La Trobe Adjustment Scheme. "
            "Adjustments are applied based on educational disadvantage and subject bonus points. "
            "The maximum adjustment is 10 ATAR points."
        ),
        "is_exception": False,
    },
]

ACADEMIC_DRESS_CHUNKS = [
    {
        "chunk_id": "grad_001",
        "document_title": "Graduation and Academic Dress Policy",
        "source_url": "https://policies.latrobe.edu.au/document/view/graduation-policy",
        "content": (
            "Doctor of Philosophy graduates wear a scarlet gown with black facings, "
            "a black and scarlet bonnet, and a scarlet hood lined with gold."
        ),
        "is_exception": False,
    },
]

# ── Test Cases ─────────────────────────────────────────────────────────────────

TEST_QUERIES = [
    {
        "id": "T01",
        "query": "What is the academic integrity policy at La Trobe?",
        "type": "grounded",
        "expected_behaviour": "policy_answer",
        "chunks": ACADEMIC_INTEGRITY_CHUNKS,
    },
    {
        "id": "T02",
        "query": "How are ATAR scores adjusted for admission?",
        "type": "grounded",
        "expected_behaviour": "policy_answer",
        "chunks": ATAR_CHUNKS,
    },
    {
        "id": "T03",
        "query": "What are the components of academic dress for a Doctor of Philosophy graduate?",
        "type": "grounded",
        "expected_behaviour": "policy_answer",
        "chunks": ACADEMIC_DRESS_CHUNKS,
    },
    {
        "id": "T04",
        "query": "What is the best pizza place near the Bundoora campus?",
        "type": "out_of_scope",
        "expected_behaviour": "fallback",
        "chunks": [],  # retrieval returns empty → backend triggers empty-chunk path
    },
    {
        "id": "T05",
        "query": "Can you help me write my assignment?",
        "type": "out_of_scope",
        "expected_behaviour": "fallback",
        "chunks": [],
    },
]

FALLBACK_PHRASE = "not covered in the provided policy"


# ── Helpers ────────────────────────────────────────────────────────────────────

def validate_output_structure(result: dict) -> list[str]:
    """Check the result dict has the required backend contract fields."""
    issues = []
    if "answer" not in result:
        issues.append("Missing 'answer' key in output.")
    elif not result["answer"].strip():
        issues.append("'answer' is empty.")
    if "used_sources" not in result:
        issues.append("Missing 'used_sources' key in output.")
    elif not isinstance(result["used_sources"], list):
        issues.append("'used_sources' must be a list.")
    return issues


def run_consistency_check(query: str, chunks: list[dict], runs: int = 3) -> bool:
    """
    Run the same query multiple times and check answers are identical.
    temperature=0 guarantees determinism.
    """
    answers = set()
    for _ in range(runs):
        r = generate_answer(question=query, chunks=chunks)
        answers.add(r["answer"].strip())
    return len(answers) == 1


def check_fallback(result: dict) -> bool:
    """Return True if the response is a fallback."""
    return FALLBACK_PHRASE.lower() in result["answer"].strip().lower()


# ── Main Test Runner ────────────────────────────────────────────────────────────

def run_all_tests():
    print("=" * 70)
    print(f"SPRINT 2 — GENERATION LAYER CONSISTENCY TESTS  [{PROMPT_VERSION}]")
    print("=" * 70)

    passed = 0
    failed = 0
    results_log = []

    for tc in TEST_QUERIES:
        print(f"\n[{tc['id']}] {tc['type'].upper()}: {tc['query'][:60]}...")

        result = generate_answer(question=tc["query"], chunks=tc["chunks"])
        answer = result["answer"].strip()
        used_sources = result.get("used_sources", [])

        # 1. Structure check
        struct_issues = validate_output_structure(result)

        # 2. Behaviour check
        is_fallback = check_fallback(result)
        if tc["expected_behaviour"] == "fallback":
            behaviour_ok = is_fallback
        else:
            behaviour_ok = not is_fallback and len(answer) > 10

        # 3. Consistency check (grounded queries only)
        if tc["type"] == "grounded":
            consistent = run_consistency_check(tc["query"], tc["chunks"])
        else:
            consistent = True

        test_passed = (not struct_issues) and behaviour_ok and consistent
        status = "✅ PASS" if test_passed else "❌ FAIL"

        print(f"  Status         : {status}")
        print(f"  Answer snippet : {answer[:120]}")
        print(f"  used_sources   : {used_sources}")
        print(f"  Structure OK   : {not struct_issues} {struct_issues or ''}")
        print(f"  Behaviour OK   : {behaviour_ok} (expected: {tc['expected_behaviour']})")
        print(f"  Consistent     : {consistent}")

        if test_passed:
            passed += 1
        else:
            failed += 1

        results_log.append({
            "id":           tc["id"],
            "query":        tc["query"],
            "answer":       answer,
            "used_sources": used_sources,
            "passed":       test_passed,
            "behaviour_ok": behaviour_ok,
            "consistent":   consistent,
            "struct_issues": struct_issues,
        })

    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed / {failed} failed out of {len(TEST_QUERIES)} tests")
    print("=" * 70)

    return results_log


if __name__ == "__main__":
    run_all_tests()
