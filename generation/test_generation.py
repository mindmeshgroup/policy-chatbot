"""
Sprint 2 - Task 5: Test Generation Output Consistency
Validates that the generation layer produces consistent, grounded outputs
and that fallback behaviour works correctly.
"""

import os
from dotenv import load_dotenv
from langchain.vectorstores import Chroma
from langchain.embeddings import HuggingFaceEmbeddings
from langchain.chat_models import ChatOpenAI
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate

load_dotenv()

# ── Configuration ──────────────────────────────────────────────────────────────
CHROMA_PATH = "./chroma_db_vlm"
COLLECTION_NAME = "latrobe_policy_v4"

# ── Setup (mirrors chatbot.py) ─────────────────────────────────────────────────
embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings,
            collection_name=COLLECTION_NAME)
retriever = db.as_retriever(search_kwargs={"k": 5})
llm = ChatOpenAI(model_name="gpt-4o-mini", temperature=0)

template = """
You are the La Trobe University Policy Chatbot.
Use ONLY the following policy context to answer the question.

If the answer is not contained in the context,
respond exactly with: "This is not covered in policy."
Do NOT make up information.

Context:
{context}

Question:
{question}

Helpful Answer:
"""
QA_PROMPT = PromptTemplate(template=template, input_variables=["context", "question"])
qa_chain = RetrievalQA.from_chain_type(
    llm=llm, chain_type="stuff", retriever=retriever,
    return_source_documents=True, chain_type_kwargs={"prompt": QA_PROMPT}
)

# ── Test Cases ─────────────────────────────────────────────────────────────────
TEST_QUERIES = [
    # Grounded queries — should produce a real policy answer
    {
        "id": "T01",
        "query": "What is the academic integrity policy at La Trobe?",
        "type": "grounded",
        "expected_behaviour": "policy_answer"
    },
    {
        "id": "T02",
        "query": "How are ATAR scores adjusted for admission?",
        "type": "grounded",
        "expected_behaviour": "policy_answer"
    },
    {
        "id": "T03",
        "query": "What are the components of academic dress for a Doctor of Philosophy graduate?",
        "type": "grounded",
        "expected_behaviour": "policy_answer"
    },
    # Fallback queries — should trigger "not covered in policy"
    {
        "id": "T04",
        "query": "What is the best pizza place near the Bundoora campus?",
        "type": "out_of_scope",
        "expected_behaviour": "fallback"
    },
    {
        "id": "T05",
        "query": "Can you help me write my assignment?",
        "type": "out_of_scope",
        "expected_behaviour": "fallback"
    },
]

FALLBACK_PHRASE = "This is not covered in policy."

# ── Helpers ────────────────────────────────────────────────────────────────────

def validate_output_structure(result: dict) -> list[str]:
    """Check the result dict has the expected keys and non-empty values."""
    issues = []
    if "result" not in result:
        issues.append("Missing 'result' key in output.")
    elif not result["result"].strip():
        issues.append("'result' is empty.")
    if "source_documents" not in result:
        issues.append("Missing 'source_documents' key in output.")
    return issues


def run_consistency_check(query: str, runs: int = 3) -> bool:
    """
    Run the same query multiple times and check that all answers are identical.
    temperature=0 should guarantee determinism.
    """
    answers = set()
    for _ in range(runs):
        r = qa_chain({"query": query})
        answers.add(r["result"].strip())
    return len(answers) == 1   # True = consistent


def check_fallback(result: dict) -> bool:
    """Return True if the response is the expected fallback phrase."""
    return FALLBACK_PHRASE.lower() in result["result"].strip().lower()


# ── Main Test Runner ────────────────────────────────────────────────────────────

def run_all_tests():
    print("=" * 70)
    print("SPRINT 2 — GENERATION LAYER CONSISTENCY TESTS")
    print("=" * 70)

    passed = 0
    failed = 0
    results_log = []

    for tc in TEST_QUERIES:
        print(f"\n[{tc['id']}] {tc['type'].upper()}: {tc['query'][:60]}...")

        result = qa_chain({"query": tc["query"]})
        answer = result["result"].strip()
        sources = result.get("source_documents", [])

        # 1. Structure check
        struct_issues = validate_output_structure(result)

        # 2. Behaviour check
        is_fallback = check_fallback(result)
        if tc["expected_behaviour"] == "fallback":
            behaviour_ok = is_fallback
        else:
            behaviour_ok = not is_fallback and len(answer) > 10

        # 3. Consistency check (only for grounded, to save API calls)
        if tc["type"] == "grounded":
            consistent = run_consistency_check(tc["query"])
        else:
            consistent = True   # skip for out-of-scope

        test_passed = (not struct_issues) and behaviour_ok and consistent

        status = "✅ PASS" if test_passed else "❌ FAIL"
        print(f"  Status         : {status}")
        print(f"  Answer snippet : {answer[:120]}")
        print(f"  Sources found  : {len(sources)}")
        print(f"  Structure OK   : {not struct_issues} {struct_issues or ''}")
        print(f"  Behaviour OK   : {behaviour_ok} (expected: {tc['expected_behaviour']})")
        print(f"  Consistent     : {consistent}")

        if test_passed:
            passed += 1
        else:
            failed += 1

        results_log.append({
            "id": tc["id"],
            "query": tc["query"],
            "answer": answer,
            "sources": [d.metadata.get("source", "?") for d in sources],
            "passed": test_passed,
            "behaviour_ok": behaviour_ok,
            "consistent": consistent,
            "struct_issues": struct_issues,
        })

    # ── Summary ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed / {failed} failed out of {len(TEST_QUERIES)} tests")
    print("=" * 70)

    return results_log


if __name__ == "__main__":
    run_all_tests()
