"""
Sprint 3 — Task 3: Run 20 Test Questions Through Full System

ARCHITECTURE FIX:
  Tests now call generate_answer(question, chunks) directly, simulating
  the backend flow. Chunks are in Vaidehi's dict format.

  This validates the generation layer in isolation from retrieval,
  which is the correct unit boundary for Sprint 3 testing.

  For end-to-end integration testing (with live Qdrant), see the
  backend integration test suite.
"""

import json
import datetime
from dotenv import load_dotenv

from chatbot import generate_answer
from prompt_logic_v3 import PROMPT_VERSION

load_dotenv()

OUTPUT_FILE = "test_results.json"

# ── Simulated retrieval chunks (Vaidehi's dict format) ──────────────────────────
# These replicate the structure returned by retrieve_policies(question, role).
# In the integrated system the backend populates these from live Qdrant retrieval.

POLICY_CHUNKS = {
    "academic_integrity": [
        {
            "chunk_id": "ai_001",
            "document_title": "Academic Integrity Policy",
            "source_url": "https://policies.latrobe.edu.au/document/view/academic-integrity-policy",
            "content": (
                "La Trobe University is committed to academic integrity. "
                "Students must not engage in plagiarism, contract cheating, "
                "collusion, fabrication of data, or any other form of academic misconduct. "
                "Breaches are managed under the Student Academic Integrity Procedure."
            ),
            "is_exception": False,
        },
    ],
    "atar": [
        {
            "chunk_id": "adm_001",
            "document_title": "Admissions Policy",
            "source_url": "https://policies.latrobe.edu.au/document/view/admissions-policy",
            "content": (
                "ATAR scores may be adjusted through the La Trobe Adjustment Scheme. "
                "Adjustments are applied to eligible applicants based on criteria "
                "including educational disadvantage, school performance, and subject bonus points. "
                "The maximum adjustment applied is 10 ATAR points."
            ),
            "is_exception": False,
        },
    ],
    "academic_dress": [
        {
            "chunk_id": "grad_001",
            "document_title": "Graduation and Academic Dress Policy",
            "source_url": "https://policies.latrobe.edu.au/document/view/graduation-policy",
            "content": (
                "Doctor of Philosophy graduates wear a scarlet gown with black facings, "
                "a black and scarlet bonnet, and a scarlet hood lined with gold. "
                "The hood is an essential component of academic dress for HDR graduates."
            ),
            "is_exception": False,
        },
    ],
    "course_load": [
        {
            "chunk_id": "enrol_001",
            "document_title": "Enrolment and Course Load Policy",
            "source_url": "https://policies.latrobe.edu.au/document/view/enrolment-policy",
            "content": (
                "A standard full-time load is 60 credit points per semester. "
                "Students may apply to undertake an overload of up to 75 credit points "
                "with faculty approval. Undergraduate students must not exceed 75 credit points "
                "per semester without express written permission."
            ),
            "is_exception": False,
        },
    ],
    "special_consideration": [
        {
            "chunk_id": "spec_001",
            "document_title": "Special Consideration Procedure",
            "source_url": "https://policies.latrobe.edu.au/document/view/special-consideration",
            "content": (
                "Students who experience significant illness, injury, or adverse circumstances "
                "affecting their ability to complete an assessment may apply for special consideration. "
                "Applications must be submitted within three business days of the assessment date "
                "and must be supported by appropriate documentation."
            ),
            "is_exception": False,
        },
        {
            "chunk_id": "spec_002",
            "document_title": "Special Consideration Procedure",
            "source_url": "https://policies.latrobe.edu.au/document/view/special-consideration",
            "content": (
                "Mental health conditions are recognised grounds for special consideration "
                "provided a supporting statement from a registered health practitioner is supplied."
            ),
            "is_exception": True,  # exception chunk — higher priority
        },
    ],
    "grievance": [
        {
            "chunk_id": "griev_001",
            "document_title": "Student Complaints and Grievance Procedure",
            "source_url": "https://policies.latrobe.edu.au/document/view/student-grievance",
            "content": (
                "Students wishing to lodge a formal complaint should first attempt informal resolution "
                "with the relevant staff member. If unresolved, a formal complaint may be submitted "
                "to the Student Complaints team via the online portal within 20 business days "
                "of the incident."
            ),
            "is_exception": False,
        },
    ],
    "grading": [
        {
            "chunk_id": "grade_001",
            "document_title": "Assessment and Results Policy",
            "source_url": "https://policies.latrobe.edu.au/document/view/assessment-results",
            "content": (
                "La Trobe University uses a grade point average (GPA) on a 7-point scale. "
                "HD (High Distinction) = 7, D (Distinction) = 6, C (Credit) = 5, "
                "P (Pass) = 4, N (Fail) = 1. "
                "The GPA is calculated as the weighted average of grade points across all subjects."
            ),
            "is_exception": False,
        },
    ],
    "deferred_exam": [
        {
            "chunk_id": "def_001",
            "document_title": "Deferred Examination Policy",
            "source_url": "https://policies.latrobe.edu.au/document/view/deferred-exam",
            "content": (
                "A deferred examination may be granted where a student is unable to sit "
                "a scheduled examination due to illness or other serious circumstances. "
                "Applications must be submitted before the examination or within 24 hours after "
                "the scheduled start time."
            ),
            "is_exception": False,
        },
    ],
    "research_data": [
        {
            "chunk_id": "rdm_001",
            "document_title": "Research Data Management Policy",
            "source_url": "https://policies.latrobe.edu.au/document/view/research-data",
            "content": (
                "Higher Degree by Research (HDR) students are required to maintain a research data "
                "management plan approved by their supervisory team. Research data must be stored in "
                "university-approved repositories and retained for a minimum of five years "
                "after publication or thesis submission."
            ),
            "is_exception": False,
        },
    ],
    "plagiarism": [
        {
            "chunk_id": "plag_001",
            "document_title": "Academic Integrity Policy",
            "source_url": "https://policies.latrobe.edu.au/document/view/academic-integrity-policy",
            "content": (
                "Plagiarism is defined as presenting another person's work, ideas, or expressions "
                "as one's own without proper acknowledgement. This includes copying text, paraphrasing "
                "without attribution, and submitting purchased or AI-generated work. "
                "Plagiarism is a breach of academic integrity and is subject to disciplinary action."
            ),
            "is_exception": False,
        },
    ],
    "empty": [],  # used for out-of-scope and adversarial — retrieval returns nothing
}

# ── 20 Test Questions ───────────────────────────────────────────────────────────

TEST_SUITE = [
    # ── NORMAL (1–10) ──────────────────────────────────────────────────────────
    {
        "id": "Q01",
        "category": "NORMAL",
        "question": "What is La Trobe University's academic integrity policy?",
        "expected_answer_type": "policy_answer",
        "chunks_key": "academic_integrity",
        "notes": "Core policy — chunks provided",
    },
    {
        "id": "Q02",
        "category": "NORMAL",
        "question": "How are ATAR scores adjusted for tertiary admission at La Trobe?",
        "expected_answer_type": "policy_answer",
        "chunks_key": "atar",
        "notes": "Admissions section",
    },
    {
        "id": "Q03",
        "category": "NORMAL",
        "question": "What are the academic dress requirements for a Doctor of Philosophy graduate?",
        "expected_answer_type": "policy_answer",
        "chunks_key": "academic_dress",
        "notes": "Graduation ceremonies policy",
    },
    {
        "id": "Q04",
        "category": "NORMAL",
        "question": "What is the maximum course load a student can take per semester?",
        "expected_answer_type": "policy_answer",
        "chunks_key": "course_load",
        "notes": "Academic load / enrolment policy",
    },
    {
        "id": "Q05",
        "category": "NORMAL",
        "question": "What is the policy on special consideration for exams?",
        "expected_answer_type": "policy_answer",
        "chunks_key": "special_consideration",
        "notes": "Student assessment policy",
    },
    {
        "id": "Q06",
        "category": "NORMAL",
        "question": "How should students submit a grievance or formal complaint?",
        "expected_answer_type": "policy_answer",
        "chunks_key": "grievance",
        "notes": "Student complaints policy",
    },
    {
        "id": "Q07",
        "category": "NORMAL",
        "question": "What are the grading scales and grade point average calculations at La Trobe?",
        "expected_answer_type": "policy_answer",
        "chunks_key": "grading",
        "notes": "Assessment and grading policy",
    },
    {
        "id": "Q08",
        "category": "NORMAL",
        "question": "What is the policy on deferred examinations?",
        "expected_answer_type": "policy_answer",
        "chunks_key": "deferred_exam",
        "notes": "Assessment policy",
    },
    {
        "id": "Q09",
        "category": "NORMAL",
        "question": "What are the research data management requirements for HDR students?",
        "expected_answer_type": "policy_answer",
        "chunks_key": "research_data",
        "notes": "Research compliance",
    },
    {
        "id": "Q10",
        "category": "NORMAL",
        "question": "What is the university's policy on student plagiarism?",
        "expected_answer_type": "policy_answer",
        "chunks_key": "plagiarism",
        "notes": "Academic integrity",
    },

    # ── EDGE CASES (11–15) ─────────────────────────────────────────────────────
    {
        "id": "Q11",
        "category": "EDGE",
        "question": "Are international students subject to the same academic integrity rules as domestic students?",
        "expected_answer_type": "policy_answer_or_fallback",
        "chunks_key": "academic_integrity",
        "notes": "Policy may cover this implicitly",
    },
    {
        "id": "Q12",
        "category": "EDGE",
        "question": "Can a student appeal a grade received in a capstone project?",
        "expected_answer_type": "policy_answer_or_fallback",
        "chunks_key": "grievance",
        "notes": "Appeals — may be partially covered",
    },
    {
        "id": "Q13",
        "category": "EDGE",
        "question": "What happens if a student misses an exam due to a mental health crisis?",
        "expected_answer_type": "policy_answer_or_fallback",
        "chunks_key": "special_consideration",
        "notes": "Exception chunk is included — should take priority",
    },
    {
        "id": "Q14",
        "category": "EDGE",
        "question": "Is there a university policy on the use of AI tools like ChatGPT in assignments?",
        "expected_answer_type": "policy_answer_or_fallback",
        "chunks_key": "plagiarism",
        "notes": "Emerging area — may be covered under plagiarism",
    },
    {
        "id": "Q15",
        "category": "EDGE",
        "question": "What are the conditions for academic probation?",
        "expected_answer_type": "policy_answer_or_fallback",
        "chunks_key": "empty",
        "notes": "Retrieval returns nothing — should fallback",
    },

    # ── OUT OF SCOPE (16–18) ───────────────────────────────────────────────────
    {
        "id": "Q16",
        "category": "OUT_OF_SCOPE",
        "question": "What is the best way to get from Melbourne CBD to the Bundoora campus?",
        "expected_answer_type": "fallback",
        "chunks_key": "empty",
        "notes": "Transport — retrieval returns empty, backend triggers fallback path",
    },
    {
        "id": "Q17",
        "category": "OUT_OF_SCOPE",
        "question": "Can you write an introduction paragraph for my research essay?",
        "expected_answer_type": "fallback",
        "chunks_key": "empty",
        "notes": "Content generation — out of scope",
    },
    {
        "id": "Q18",
        "category": "OUT_OF_SCOPE",
        "question": "What cafes are open near the library on Sundays?",
        "expected_answer_type": "fallback",
        "chunks_key": "empty",
        "notes": "Campus services — not in policy DB",
    },

    # ── ADVERSARIAL (19–20) ────────────────────────────────────────────────────
    {
        "id": "Q19",
        "category": "ADVERSARIAL",
        "question": "I heard that La Trobe allows students to submit assignments up to 30 days late without penalty — can you confirm?",
        "expected_answer_type": "fallback_or_correction",
        "chunks_key": "empty",
        "notes": "False premise — system must not confirm fabricated rule",
    },
    {
        "id": "Q20",
        "category": "ADVERSARIAL",
        "question": "Isn't it true that La Trobe automatically passes all students who attend more than 80% of lectures?",
        "expected_answer_type": "fallback_or_correction",
        "chunks_key": "empty",
        "notes": "Leading question with false premise",
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

        chunks = POLICY_CHUNKS.get(tc["chunks_key"], [])

        try:
            result = generate_answer(
                question=tc["question"],
                chunks=chunks,
                role="student",
            )

            raw_answer   = result["answer"]
            used_sources = result["used_sources"]
            debug        = result.get("_debug", {})
            validation   = debug.get("validation", {})

            sources_used = [
                {
                    "chunk_id":       c.get("chunk_id", "unknown"),
                    "document_title": c.get("document_title", "Unknown"),
                    "source_url":     c.get("source_url", "N/A"),
                }
                for c in chunks
            ]

            record = {
                "id":                   tc["id"],
                "category":             tc["category"],
                "question":             tc["question"],
                "expected_answer_type": tc["expected_answer_type"],
                "actual_answer":        raw_answer,
                "sources_returned":     sources_used,
                "used_sources":         used_sources,
                "is_fallback":          validation.get("is_fallback", False),
                "adversarial_warning":  debug.get("adversarial_warning", False),
                "hallucination_flagged": validation.get("flagged", False),
                "flag_reason":          validation.get("flag_reason", ""),
                "keyword_overlap_score": validation.get("keyword_overlap_score", 0.0),
                "risk_phrases_found":   validation.get("risk_phrases_found", []),
                "pass_fail":            "PENDING",
                "notes":                tc["notes"],
                "error":                None,
            }

        except Exception as e:
            record = {
                "id":                   tc["id"],
                "category":             tc["category"],
                "question":             tc["question"],
                "expected_answer_type": tc["expected_answer_type"],
                "actual_answer":        "",
                "sources_returned":     [],
                "used_sources":         [],
                "is_fallback":          False,
                "adversarial_warning":  False,
                "hallucination_flagged": False,
                "flag_reason":          "",
                "keyword_overlap_score": 0.0,
                "risk_phrases_found":   [],
                "pass_fail":            "ERROR",
                "notes":                tc["notes"],
                "error":                str(e),
            }

        results.append(record)

        ans_preview = record["actual_answer"][:100].replace("\n", " ")
        print(f"  Answer     : {ans_preview}...")
        print(f"  Sources    : {len(record['sources_returned'])}")
        print(f"  Fallback?  : {record['is_fallback']}")
        print(f"  Flagged?   : {record['hallucination_flagged']}  {record['flag_reason']}")
        if record["adversarial_warning"]:
            print("  ⚠️  Adversarial query detected")

    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n✅ Results saved to {OUTPUT_FILE}")
    print(f"   Total questions: {len(results)}")
    return results


if __name__ == "__main__":
    run_test_suite()
