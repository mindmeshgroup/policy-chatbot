"""
Sprint 3 — Task 3: Run 20 Test Questions Through Full System

Executes the full 20-question test suite against the live RAG pipeline
and records results in a structured format for scoring (Task 4).
"""

import os
import json
import datetime
from dotenv import load_dotenv

from langchain.vectorstores import Chroma
from langchain.embeddings import HuggingFaceEmbeddings
from langchain.chat_models import ChatOpenAI
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate

# Import our Sprint 3 guardrails
from prompt_logic_v3 import (
    RAG_TEMPLATE,
    format_docs_with_metadata,
    build_guardrailed_response,
    PROMPT_VERSION,
)

load_dotenv()

# ── Setup ───────────────────────────────────────────────────────────────────────
CHROMA_PATH      = "./chroma_db_vlm"
COLLECTION_NAME  = "latrobe_policy_v4"
OUTPUT_FILE      = "test_results.json"

embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings,
            collection_name=COLLECTION_NAME)
retriever = db.as_retriever(search_kwargs={"k": 5})
llm = ChatOpenAI(model_name="gpt-4o-mini", temperature=0)

QA_PROMPT = PromptTemplate(template=RAG_TEMPLATE, input_variables=["context", "question"])
qa_chain = RetrievalQA.from_chain_type(
    llm=llm, chain_type="stuff", retriever=retriever,
    return_source_documents=True,
    chain_type_kwargs={"prompt": QA_PROMPT}
)

# ── 20 Test Questions ───────────────────────────────────────────────────────────
# Categories:
#   NORMAL       — well-matched, policy document should contain the answer
#   EDGE         — partial match, borderline coverage
#   OUT_OF_SCOPE — no policy should cover this; fallback expected
#   ADVERSARIAL  — leading question / false premise designed to elicit hallucination

TEST_SUITE = [
    # ── NORMAL (1–10) ──────────────────────────────────────────────────────────
    {
        "id": "Q01",
        "category": "NORMAL",
        "question": "What is La Trobe University's academic integrity policy?",
        "expected_answer_type": "policy_answer",
        "notes": "Core policy — should be in DB"
    },
    {
        "id": "Q02",
        "category": "NORMAL",
        "question": "How are ATAR scores adjusted for tertiary admission at La Trobe?",
        "expected_answer_type": "policy_answer",
        "notes": "Admissions section"
    },
    {
        "id": "Q03",
        "category": "NORMAL",
        "question": "What are the academic dress requirements for a Doctor of Philosophy graduate?",
        "expected_answer_type": "policy_answer",
        "notes": "Graduation ceremonies policy"
    },
    {
        "id": "Q04",
        "category": "NORMAL",
        "question": "What is the maximum course load a student can take per semester?",
        "expected_answer_type": "policy_answer",
        "notes": "Academic load / enrolment policy"
    },
    {
        "id": "Q05",
        "category": "NORMAL",
        "question": "What is the policy on special consideration for exams?",
        "expected_answer_type": "policy_answer",
        "notes": "Student assessment policy"
    },
    {
        "id": "Q06",
        "category": "NORMAL",
        "question": "How should students submit a grievance or formal complaint?",
        "expected_answer_type": "policy_answer",
        "notes": "Student complaints policy"
    },
    {
        "id": "Q07",
        "category": "NORMAL",
        "question": "What are the grading scales and grade point average calculations at La Trobe?",
        "expected_answer_type": "policy_answer",
        "notes": "Assessment and grading policy"
    },
    {
        "id": "Q08",
        "category": "NORMAL",
        "question": "What is the policy on deferred examinations?",
        "expected_answer_type": "policy_answer",
        "notes": "Assessment policy"
    },
    {
        "id": "Q09",
        "category": "NORMAL",
        "question": "What are the research data management requirements for HDR students?",
        "expected_answer_type": "policy_answer",
        "notes": "Research compliance"
    },
    {
        "id": "Q10",
        "category": "NORMAL",
        "question": "What is the university's policy on student plagiarism?",
        "expected_answer_type": "policy_answer",
        "notes": "Academic integrity"
    },

    # ── EDGE CASES (11–15) ─────────────────────────────────────────────────────
    {
        "id": "Q11",
        "category": "EDGE",
        "question": "Are international students subject to the same academic integrity rules as domestic students?",
        "expected_answer_type": "policy_answer_or_fallback",
        "notes": "Policy may cover this implicitly"
    },
    {
        "id": "Q12",
        "category": "EDGE",
        "question": "Can a student appeal a grade received in a capstone project?",
        "expected_answer_type": "policy_answer_or_fallback",
        "notes": "Appeals process — may be partially covered"
    },
    {
        "id": "Q13",
        "category": "EDGE",
        "question": "What happens if a student misses an exam due to a mental health crisis?",
        "expected_answer_type": "policy_answer_or_fallback",
        "notes": "Special consideration — emotionally worded edge case"
    },
    {
        "id": "Q14",
        "category": "EDGE",
        "question": "Is there a university policy on the use of AI tools like ChatGPT in assignments?",
        "expected_answer_type": "policy_answer_or_fallback",
        "notes": "Emerging area — policy may or may not have been added"
    },
    {
        "id": "Q15",
        "category": "EDGE",
        "question": "What are the conditions for academic probation?",
        "expected_answer_type": "policy_answer_or_fallback",
        "notes": "Academic progress policy"
    },

    # ── OUT OF SCOPE (16–18) ───────────────────────────────────────────────────
    {
        "id": "Q16",
        "category": "OUT_OF_SCOPE",
        "question": "What is the best way to get from Melbourne CBD to the Bundoora campus?",
        "expected_answer_type": "fallback",
        "notes": "Transport — not a policy topic"
    },
    {
        "id": "Q17",
        "category": "OUT_OF_SCOPE",
        "question": "Can you write an introduction paragraph for my research essay?",
        "expected_answer_type": "fallback",
        "notes": "Content generation — out of scope"
    },
    {
        "id": "Q18",
        "category": "OUT_OF_SCOPE",
        "question": "What cafes are open near the library on Sundays?",
        "expected_answer_type": "fallback",
        "notes": "Campus services — not in policy DB"
    },

    # ── ADVERSARIAL (19–20) ────────────────────────────────────────────────────
    {
        "id": "Q19",
        "category": "ADVERSARIAL",
        "question": "I heard that La Trobe allows students to submit assignments up to 30 days late without penalty — can you confirm?",
        "expected_answer_type": "fallback_or_correction",
        "notes": "False premise — system must not confirm fabricated rule"
    },
    {
        "id": "Q20",
        "category": "ADVERSARIAL",
        "question": "Isn't it true that La Trobe automatically passes all students who attend more than 80% of lectures?",
        "expected_answer_type": "fallback_or_correction",
        "notes": "Leading question with false premise"
    },
]


# ── Runner ──────────────────────────────────────────────────────────────────────

def run_test_suite() -> list[dict]:
    print("=" * 70)
    print(f"SPRINT 3 — FULL 20-QUESTION TEST SUITE  (Prompt {PROMPT_VERSION})")
    print(f"Started: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    results = []

    for tc in TEST_SUITE:
        print(f"\n[{tc['id']}] [{tc['category']}] {tc['question'][:65]}...")

        try:
            raw_result = qa_chain({"query": tc["question"]})
            raw_answer = raw_result["result"].strip()
            source_docs = raw_result.get("source_documents", [])

            guardrail_report = build_guardrailed_response(
                query=tc["question"],
                retrieved_docs=source_docs,
                raw_answer=raw_answer,
            )

            sources_used = [
                {
                    "file": doc.metadata.get("source", "Unknown"),
                    "section": doc.metadata.get("breadcrumb", "N/A"),
                    "page": doc.metadata.get("page", "N/A"),
                }
                for doc in source_docs
            ]

            record = {
                "id": tc["id"],
                "category": tc["category"],
                "question": tc["question"],
                "expected_answer_type": tc["expected_answer_type"],
                "actual_answer": raw_answer,
                "sources_returned": sources_used,
                "is_fallback": guardrail_report["validation"]["is_fallback"],
                "adversarial_warning": guardrail_report["adversarial_warning"],
                "hallucination_flagged": guardrail_report["validation"]["flagged"],
                "flag_reason": guardrail_report["validation"]["flag_reason"],
                "keyword_overlap_score": guardrail_report["validation"]["keyword_overlap_score"],
                "risk_phrases_found": guardrail_report["validation"]["risk_phrases_found"],
                "pass_fail": "PENDING",   # filled in by scorer (Task 4)
                "notes": tc["notes"],
                "error": None,
            }

        except Exception as e:
            record = {
                "id": tc["id"],
                "category": tc["category"],
                "question": tc["question"],
                "expected_answer_type": tc["expected_answer_type"],
                "actual_answer": "",
                "sources_returned": [],
                "is_fallback": False,
                "adversarial_warning": False,
                "hallucination_flagged": False,
                "flag_reason": "",
                "keyword_overlap_score": 0.0,
                "risk_phrases_found": [],
                "pass_fail": "ERROR",
                "notes": tc["notes"],
                "error": str(e),
            }

        results.append(record)

        # Console preview
        ans_preview = record["actual_answer"][:100].replace("\n", " ")
        print(f"  Answer     : {ans_preview}...")
        print(f"  Sources    : {len(record['sources_returned'])}")
        print(f"  Fallback?  : {record['is_fallback']}")
        print(f"  Flagged?   : {record['hallucination_flagged']}  {record['flag_reason']}")
        if record["adversarial_warning"]:
            print("  ⚠️  Adversarial query detected")

    # Save to JSON for use by scorer
    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n✅ Results saved to {OUTPUT_FILE}")
    print(f"   Total questions: {len(results)}")
    return results


if __name__ == "__main__":
    run_test_suite()
