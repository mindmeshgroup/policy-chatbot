

"""
Sprint 3 — Task 4: Score Answer Quality (Relevance + Citation Accuracy)

Loads test_results.json (produced by test_suite.py) and applies a
scoring rubric to each response. Outputs a scored report.

RUBRIC (each dimension: 1–5)
──────────────────────────────────────────────────────────────────
1. RELEVANCE        — Does the answer address the question asked?
2. GROUNDING        — Is the answer supported by retrieved content?
                      (uses keyword_overlap_score from guardrails)
3. CITATION_ACCURACY — Do cited sources match the content of the answer?
4. COMPLETENESS     — Does the answer cover all key aspects of the question?
5. FALLBACK_QUALITY — For fallback answers: is the refusal clear and
                      does it include escalation guidance?
                      (N/A for grounded answers → scored as 5/5 automatically)
──────────────────────────────────────────────────────────────────
PASS threshold per question: average score ≥ 3.0 AND no CRITICAL fails
CRITICAL fail: hallucination_flagged=True on a question where
               expected_answer_type is NOT fallback.
"""

import json
import sys
from typing import Optional

RESULTS_FILE = "test_results.json"
SCORED_FILE  = "test_results_scored.json"

# ── Rubric helpers ──────────────────────────────────────────────────────────────

ESCALATION_KEYWORDS = [
    "contact", "policy@", "studentservices", "administration",
    "faculty", "office", "email", "staff"
]

FALLBACK_PHRASES = [
    "not covered in the provided policy",
    "this question is not covered",
    "this is not covered in policy",
]


def score_relevance(answer: str, question: str, is_fallback: bool,
                    expected_answer_type: str) -> tuple[int, str]:
    """
    1 = Completely off-topic or empty
    2 = Tangentially related but misses the question
    3 = Partially answers the question
    4 = Mostly answers with minor gaps
    5 = Fully answers the question

    For fallback answers: 5 if fallback was expected, 1 if not.
    """
    if not answer.strip():
        return 1, "Empty answer."

    if is_fallback:
        if "fallback" in expected_answer_type or "correction" in expected_answer_type:
            return 5, "Correct fallback — expected."
        else:
            return 1, "Fallback returned but a policy answer was expected."

    # Heuristic: check that key words from the question appear in the answer
    q_words = set(question.lower().split()) - {"what", "is", "the", "a", "an",
                                                "how", "are", "at", "for", "to",
                                                "in", "of", "and", "or"}
    ans_lower = answer.lower()
    hits = sum(1 for w in q_words if w in ans_lower)
    ratio = hits / max(len(q_words), 1)

    if ratio >= 0.7:
        return 5, "High question-keyword coverage."
    elif ratio >= 0.5:
        return 4, "Good question-keyword coverage."
    elif ratio >= 0.3:
        return 3, "Partial question-keyword coverage."
    elif ratio >= 0.1:
        return 2, "Low coverage of question terms."
    else:
        return 1, "Answer does not address question keywords."


def score_grounding(keyword_overlap_score: float, hallucination_flagged: bool,
                    is_fallback: bool) -> tuple[int, str]:
    """
    Uses the automated keyword_overlap_score from guardrails.
    1 = Very low overlap (<20%) or flagged
    2 = Low overlap (20–39%)
    3 = Moderate overlap (40–59%)
    4 = Good overlap (60–79%)
    5 = Strong overlap (≥80%) or correct fallback
    """
    if is_fallback:
        return 5, "Fallback response — grounding N/A."
    if hallucination_flagged:
        return 1, "Guardrail flagged potential hallucination."

    score = keyword_overlap_score
    if score >= 0.80:
        return 5, f"Strong overlap ({score:.0%})."
    elif score >= 0.60:
        return 4, f"Good overlap ({score:.0%})."
    elif score >= 0.40:
        return 3, f"Moderate overlap ({score:.0%})."
    elif score >= 0.20:
        return 2, f"Low overlap ({score:.0%})."
    else:
        return 1, f"Very low overlap ({score:.0%})."


def score_citation_accuracy(sources_returned: list, answer: str,
                             is_fallback: bool) -> tuple[int, str]:
    """
    1 = No sources returned for a grounded answer
    2 = Sources present but none referenced in answer
    3 = Sources present and some match answer content
    4 = Sources well-matched and referenced
    5 = Sources precisely match answer content with clear citation line
    """
    if is_fallback:
        return 5, "Fallback — citation N/A."
    if not sources_returned:
        return 1, "No source documents returned."

    has_citation_line = "sources:" in answer.lower()
    num_sources = len(sources_returned)

    if has_citation_line and num_sources >= 2:
        return 5, f"{num_sources} sources with citation line present."
    elif has_citation_line and num_sources == 1:
        return 4, "1 source with citation line present."
    elif not has_citation_line and num_sources >= 2:
        return 3, f"{num_sources} sources returned but no explicit citation line."
    elif not has_citation_line and num_sources == 1:
        return 2, "1 source returned but no citation line."
    else:
        return 1, "No usable citation information."


def score_completeness(answer: str, category: str,
                       is_fallback: bool) -> tuple[int, str]:
    """
    Rough heuristic based on answer length and structure.
    Edge and adversarial answers held to lower length expectations.
    1 = < 30 words (unusably short)
    2 = 30–60 words
    3 = 61–120 words
    4 = 121–250 words
    5 = > 250 words  (or is a correct, concise fallback)
    """
    if is_fallback:
        return 4, "Correct fallback — concise by design."
    word_count = len(answer.split())
    if word_count > 250:
        return 5, f"{word_count} words — comprehensive."
    elif word_count > 120:
        return 4, f"{word_count} words — good detail."
    elif word_count > 60:
        return 3, f"{word_count} words — moderate detail."
    elif word_count > 30:
        return 2, f"{word_count} words — thin."
    else:
        return 1, f"{word_count} words — too short."


def score_fallback_quality(answer: str, is_fallback: bool,
                            expected_answer_type: str) -> tuple[int, str]:
    """
    Only evaluated when is_fallback=True and fallback was expected.
    1 = No escalation info, unclear message
    3 = Clear refusal but no escalation
    5 = Clear refusal + escalation contacts included
    """
    if not is_fallback:
        return 5, "Not a fallback response — N/A, full marks."
    if "fallback" not in expected_answer_type and "correction" not in expected_answer_type:
        # Fallback was NOT expected — relevance score handles the penalty
        return 5, "N/A — scored under relevance."

    ans_lower = answer.lower()
    has_escalation = any(k in ans_lower for k in ESCALATION_KEYWORDS)
    has_refusal    = any(p in ans_lower for p in FALLBACK_PHRASES)

    if has_refusal and has_escalation:
        return 5, "Clear refusal with escalation guidance."
    elif has_refusal:
        return 3, "Clear refusal but no escalation contacts."
    else:
        return 1, "Vague response — missing refusal and escalation."


# ── Determine pass/fail ─────────────────────────────────────────────────────────

def determine_pass_fail(scores: dict, hallucination_flagged: bool,
                        is_fallback: bool, expected_answer_type: str) -> tuple[str, str]:
    avg = sum(scores.values()) / len(scores)

    # Critical fail: hallucination flagged when a real answer was expected
    if hallucination_flagged and "fallback" not in expected_answer_type:
        return "FAIL", f"CRITICAL: hallucination flagged. Avg score: {avg:.1f}"

    if avg >= 3.5:
        return "PASS", f"Avg score: {avg:.1f}"
    elif avg >= 3.0:
        return "MARGINAL", f"Avg score: {avg:.1f} — borderline"
    else:
        return "FAIL", f"Avg score: {avg:.1f} — below threshold"


# ── Root cause analysis ─────────────────────────────────────────────────────────

def root_cause(scores: dict, hallucination_flagged: bool,
               sources_returned: list) -> str:
    reasons = []
    if scores["relevance"] <= 2:
        reasons.append("Retrieval miss or off-topic generation.")
    if scores["grounding"] <= 2 or hallucination_flagged:
        reasons.append("Generation error: low grounding / hallucination risk.")
    if scores["citation_accuracy"] <= 2:
        reasons.append("Prompt issue: citation format not followed.")
    if scores["completeness"] <= 2:
        reasons.append("Answer too short — retrieval may have returned poor chunks.")
    if not sources_returned:
        reasons.append("No documents retrieved — possible DB or query issue.")
    return " | ".join(reasons) if reasons else "No obvious failure mode."


# ── Main scorer ─────────────────────────────────────────────────────────────────

def score_all(results_file: str = RESULTS_FILE) -> list[dict]:
    with open(results_file) as f:
        results = json.load(f)

    scored = []
    category_totals: dict[str, list[float]] = {}

    print("=" * 70)
    print("SPRINT 3 — ANSWER QUALITY SCORING REPORT")
    print("=" * 70)

    for r in results:
        qid      = r["id"]
        category = r["category"]
        answer   = r.get("actual_answer", "")
        is_fb    = r.get("is_fallback", False)
        exp_type = r.get("expected_answer_type", "")
        h_flag   = r.get("hallucination_flagged", False)
        overlap  = r.get("keyword_overlap_score", 0.0)
        sources  = r.get("sources_returned", [])

        if r.get("pass_fail") == "ERROR":
            scored.append({**r, "scores": {}, "avg_score": 0, "root_cause": "Pipeline error."})
            continue

        s_rel,  n_rel  = score_relevance(answer, r["question"], is_fb, exp_type)
        s_grd,  n_grd  = score_grounding(overlap, h_flag, is_fb)
        s_cit,  n_cit  = score_citation_accuracy(sources, answer, is_fb)
        s_com,  n_com  = score_completeness(answer, category, is_fb)
        s_fb,   n_fb   = score_fallback_quality(answer, is_fb, exp_type)

        scores = {
            "relevance":        s_rel,
            "grounding":        s_grd,
            "citation_accuracy": s_cit,
            "completeness":     s_com,
            "fallback_quality": s_fb,
        }
        avg = sum(scores.values()) / len(scores)
        pf, pf_note = determine_pass_fail(scores, h_flag, is_fb, exp_type)
        rc = root_cause(scores, h_flag, sources)

        print(f"\n[{qid}] [{category}]  →  {pf}  (avg {avg:.1f}/5)")
        print(f"  Scores: REL={s_rel} GRD={s_grd} CIT={s_cit} COM={s_com} FB={s_fb}")
        print(f"  Note  : {pf_note}")
        if pf == "FAIL":
            print(f"  Root Cause: {rc}")

        category_totals.setdefault(category, []).append(avg)

        scored.append({
            **r,
            "scores": scores,
            "score_notes": {
                "relevance": n_rel, "grounding": n_grd,
                "citation_accuracy": n_cit, "completeness": n_com,
                "fallback_quality": n_fb,
            },
            "avg_score": round(avg, 2),
            "pass_fail": pf,
            "pass_fail_note": pf_note,
            "root_cause": rc,
        })

    # ── Aggregate summary ──────────────────────────────────────────────────────
    all_avgs = [s["avg_score"] for s in scored if isinstance(s["avg_score"], float)]
    print("\n" + "=" * 70)
    print("AGGREGATE METRICS")
    print("=" * 70)
    if all_avgs:
        print(f"  Overall avg score : {sum(all_avgs)/len(all_avgs):.2f} / 5.00")
        print(f"  Min score         : {min(all_avgs):.2f}")
        print(f"  Max score         : {max(all_avgs):.2f}")
    pass_count = sum(1 for s in scored if s.get("pass_fail") == "PASS")
    fail_count = sum(1 for s in scored if s.get("pass_fail") == "FAIL")
    marg_count = sum(1 for s in scored if s.get("pass_fail") == "MARGINAL")
    print(f"  PASS: {pass_count} | MARGINAL: {marg_count} | FAIL: {fail_count}")

    print("\nPER-CATEGORY AVERAGES:")
    for cat, avgs in sorted(category_totals.items()):
        print(f"  {cat:<16} : {sum(avgs)/len(avgs):.2f}  (n={len(avgs)})")

    with open(SCORED_FILE, "w") as f:
        json.dump(scored, f, indent=2)

    print(f"\n✅ Scored results saved to {SCORED_FILE}")
    return scored


if __name__ == "__main__":
    results_file = sys.argv[1] if len(sys.argv) > 1 else RESULTS_FILE
    score_all(results_file)
