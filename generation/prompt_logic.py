"""
Sprint 3 — Task 1: Strengthen Hallucination Guardrails
Sprint 3 — Task 2: Strengthen "No Policy Found" Fallback Response

This module replaces/upgrades the Sprint 1 prompt_logic.py with:
  - Tighter grounding directives in the system prompt
  - A post-generation keyword-overlap validator
  - Improved, escalation-aware fallback messages
  - Adversarial query detection
"""

from langchain_core.prompts import ChatPromptTemplate

# ── Version tracking ────────────────────────────────────────────────────────────
PROMPT_VERSION = "v3.0"

# ── Sprint 3 hardened prompt ────────────────────────────────────────────────────
# Changes from Sprint 1:
#  • Added "STRICT GROUNDING RULES" block (new)
#  • Added "FORBIDDEN BEHAVIOURS" block (new)
#  • Added escalation instruction in fallback (new)
#  • Citation format enforced more explicitly (tightened)

RAG_TEMPLATE = """
You are the La Trobe University Policy Assistant.
Your ONLY role is to answer questions using the exact policy text provided below.

══════════════════════════════════════════════════════════════════
STRICT GROUNDING RULES — READ BEFORE ANSWERING
══════════════════════════════════════════════════════════════════
1. CONTEXT ONLY: Use EXCLUSIVELY the text provided in the CONTEXT block.
   Do NOT use prior knowledge, general university norms, or assumptions.
2. NO INFERENCE: Do not infer, extrapolate, or fill gaps with logic.
   If the context does not state it explicitly, it is NOT the answer.
3. EXACT DETAILS: Numbers, dates, names, and percentages must be
   copied verbatim from the context — never estimated.
4. NO COMBINING: Do not combine unrelated context chunks to construct
   an answer that no single source supports.

FORBIDDEN BEHAVIOURS (will be detected and flagged):
✗ Making up policy rules, dates, or figures not found in the context
✗ Saying "typically", "usually", or "generally" unless that exact word
  appears in the source text
✗ Speculating about what a policy "might" mean
✗ Answering a question that is not addressed in the context at all

══════════════════════════════════════════════════════════════════
FALLBACK RULE (when context does not contain the answer)
══════════════════════════════════════════════════════════════════
If the CONTEXT does not contain information sufficient to answer
the question, respond with EXACTLY this message (no additions):

  "This question is not covered in the provided policy documents.
   For authoritative guidance, please contact:
   • La Trobe University Policy team: policy@latrobe.edu.au
   • Student Services: studentservices@latrobe.edu.au
   • Your faculty's Student Administration office"

══════════════════════════════════════════════════════════════════
CITATION RULE
══════════════════════════════════════════════════════════════════
At the end of every answer (except fallbacks), list ALL sources used:
  Format: Sources: [Filename], Page [Number]
  If page number is unavailable, write: Sources: [Filename], Section: [Section Name]

══════════════════════════════════════════════════════════════════
CONTEXT
══════════════════════════════════════════════════════════════════
{context}

══════════════════════════════════════════════════════════════════
QUESTION
══════════════════════════════════════════════════════════════════
{question}

══════════════════════════════════════════════════════════════════
ANSWER
══════════════════════════════════════════════════════════════════
"""

prompt_template = ChatPromptTemplate.from_template(RAG_TEMPLATE)


# ── Context Formatter ───────────────────────────────────────────────────────────

def format_docs_with_metadata(docs: list) -> str:
    """
    Converts retrieved LangChain Document objects into a clearly labelled
    context block the LLM can reason over.
    """
    if not docs:
        return ""

    formatted_chunks = []
    for i, doc in enumerate(docs):
        source_file = doc.metadata.get("source", "Unknown File")
        breadcrumb  = doc.metadata.get("breadcrumb", "General Document")
        page_num    = doc.metadata.get("page", "N/A")
        audience    = doc.metadata.get("audience", "Unknown")
        category    = doc.metadata.get("category", "Unknown")

        header = (
            f"[CHUNK {i+1}] SOURCE: {source_file} | "
            f"PAGE: {page_num} | SECTION: {breadcrumb} | "
            f"AUDIENCE: {audience} | CATEGORY: {category}"
        )
        formatted_chunks.append(f"{header}\n{doc.page_content}")

    return "\n\n---\n\n".join(formatted_chunks)


# ── Post-generation Hallucination Validator ─────────────────────────────────────

FALLBACK_MARKERS = [
    "not covered in the provided policy",
    "this question is not covered",
    "this is not covered in policy",
]

HALLUCINATION_RISK_PHRASES = [
    "typically", "usually", "generally", "often", "in most cases",
    "it is expected", "it is assumed", "should be", "would be",
    "as far as I know", "I believe", "probably", "possibly",
]


def validate_response(answer: str, retrieved_docs: list) -> dict:
    """
    Post-generation check comparing the answer against the retrieved chunks.

    Returns a report dict:
      {
        "is_fallback": bool,
        "risk_phrases_found": list[str],
        "keyword_overlap_score": float,   # 0.0 – 1.0
        "flagged": bool,
        "flag_reason": str
      }
    """
    answer_lower = answer.lower()

    # Check if it's a fallback response
    is_fallback = any(m in answer_lower for m in FALLBACK_MARKERS)
    if is_fallback:
        return {
            "is_fallback": True,
            "risk_phrases_found": [],
            "keyword_overlap_score": 1.0,  # fallback is always "grounded"
            "flagged": False,
            "flag_reason": "",
        }

    # Detect suspicious hedging language
    risk_phrases_found = [p for p in HALLUCINATION_RISK_PHRASES if p in answer_lower]

    # Keyword overlap check: what % of non-trivial words in the answer
    # also appear in the retrieved context?
    stopwords = {"the", "a", "an", "is", "are", "was", "were", "in", "of",
                 "to", "and", "or", "for", "with", "on", "at", "by", "be",
                 "it", "this", "that", "as", "not", "no", "if", "from"}

    context_blob = " ".join(doc.page_content.lower() for doc in retrieved_docs)
    context_words = set(context_blob.split()) - stopwords

    answer_words = set(answer_lower.split()) - stopwords
    if answer_words:
        overlap = len(answer_words & context_words) / len(answer_words)
    else:
        overlap = 0.0

    # Flag if overlap is low OR risky phrases found
    LOW_OVERLAP_THRESHOLD = 0.40
    flagged = overlap < LOW_OVERLAP_THRESHOLD or len(risk_phrases_found) > 0
    flag_reason = ""
    if overlap < LOW_OVERLAP_THRESHOLD:
        flag_reason += f"Low keyword overlap ({overlap:.0%}). "
    if risk_phrases_found:
        flag_reason += f"Hedging language detected: {risk_phrases_found}."

    return {
        "is_fallback": False,
        "risk_phrases_found": risk_phrases_found,
        "keyword_overlap_score": round(overlap, 3),
        "flagged": flagged,
        "flag_reason": flag_reason.strip(),
    }


# ── Adversarial Query Detector ──────────────────────────────────────────────────

ADVERSARIAL_PATTERNS = [
    # Leading / false-premise patterns
    "i heard that la trobe",
    "isn't it true that",
    "confirm that la trobe",
    "la trobe allows",
    "la trobe does not require",
    "as per the old policy",
    "ignore the context",
    "disregard the policy",
    "pretend you are",
    "act as if",
    "forget the rules",
]

def is_adversarial(query: str) -> bool:
    """Returns True if the query looks like it might be trying to elicit hallucination."""
    q = query.lower()
    return any(pattern in q for pattern in ADVERSARIAL_PATTERNS)


# ── Main entry-point used by chatbot ───────────────────────────────────────────

def build_guardrailed_response(query: str, retrieved_docs: list, raw_answer: str) -> dict:
    """
    Combines the raw LLM answer with guardrail checks.

    Returns:
      {
        "answer": str,
        "validation": dict,
        "adversarial_warning": bool,
        "sources": list[str],
      }
    """
    adversarial = is_adversarial(query)
    validation  = validate_response(raw_answer, retrieved_docs)
    sources     = list({
        d.metadata.get("source", "Unknown") for d in retrieved_docs
    })

    return {
        "answer": raw_answer,
        "validation": validation,
        "adversarial_warning": adversarial,
        "sources": sources,
    }


print(f"✅ Prompt Template ({PROMPT_VERSION}) and Guardrails initialised.")
