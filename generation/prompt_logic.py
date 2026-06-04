"""
Sprint 3 — Task 1: Strengthen Hallucination Guardrails
Sprint 3 — Task 2: Strengthen "No Policy Found" Fallback Response

ARCHITECTURE FIX (Sprint 4 integration):
  This module is now designed to work with the integrated backend flow:
    Frontend → Backend /ask → Vaidehi Retrieval → generate_answer() → Backend Response

  It no longer owns retrieval. It accepts Vaidehi's dict-format chunks:
    chunk["content"], chunk["document_title"], chunk["source_url"],
    chunk["chunk_id"], chunk["is_exception"]

  Output format matches backend contract:
    {"answer": str, "used_sources": list[str]}
"""

# Version tracking
PROMPT_VERSION = "v3.2"

# Sprint 3 hardened prompt (updated for integrated architecture)
# Changes from v3.0:
#  Removed citation-writing instruction — backend handles citations from metadata
#  Added exception-chunk awareness (is_exception flag)
#  Context block now uses document_title/source_url from Vaidehi's retrieval format
# Changes from v3.1:
#  Added role-based audience instruction (student vs staff)
#  Stripped chunk metadata from headers to prevent LLM leakage
#  Added explicit rules against exposing internal reasoning or chunk references
#  Tightened fallback rule to prevent preamble/reasoning before fallback message

#Role-based response styling

ROLE_INSTRUCTIONS = {
    "student": (
        "You are speaking to a STUDENT.\n"
        "- Use clear, simple, and supportive language.\n"
        "- Avoid jargon — if a policy term is used, briefly explain what it means.\n"
        "- Where relevant, include practical next steps the student can take "
        "(e.g. who to contact, where to submit forms).\n"
        "- Be encouraging and approachable in tone."
    ),
    "staff": (
        "You are speaking to a STAFF MEMBER.\n"
        "- Use professional, concise language appropriate for university staff.\n"
        "- You may use policy terminology without extra explanation.\n"
        "- Focus on procedural detail, responsibilities, and compliance requirements.\n"
        "- Reference specific policy clauses or sections where the context provides them."
    ),
}

DEFAULT_ROLE = "student"


# RAG Prompt Template 

RAG_TEMPLATE = """
You are the La Trobe University Policy Assistant.
Your ONLY role is to answer questions using the exact policy text provided below.

══════════════════════════════════════════════════════════════════
AUDIENCE
══════════════════════════════════════════════════════════════════
{role_instruction}

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
5. EXCEPTION CHUNKS: Any chunk marked [EXCEPTION] describes a specific
   override or special case. Treat it as higher priority than general rules.
6. ANSWER STYLE: Write your answer in plain, natural language. Do NOT
   reference chunk numbers, document titles, URLs, or any metadata
   labels from the context. Just answer the question directly.

FORBIDDEN BEHAVIOURS (will be detected and flagged):
✗ Making up policy rules, dates, or figures not found in the context
✗ Saying "typically", "usually", or "generally" unless that exact word
  appears in the source text
✗ Speculating about what a policy "might" mean
✗ Answering a question that is not addressed in the context at all
✗ Writing source filenames, URLs, page numbers, chunk IDs, or document
  titles — the system handles citations automatically. NEVER say
  "According to [CHUNK...]" or reference any metadata labels from the
  context block.
✗ Explaining your reasoning process or referencing these instructions
  (e.g. NEVER say "According to the Fallback Rule" or "Since the context
  does not contain..." — just give the answer or the fallback directly)
✗ Repeating the same information twice in one response

══════════════════════════════════════════════════════════════════
FALLBACK RULE (when context does not contain the answer)
══════════════════════════════════════════════════════════════════
If the CONTEXT does not contain information sufficient to answer
the question, respond with EXACTLY this message and NOTHING ELSE.
Do NOT explain why you are using this response. Do NOT add any
preamble, reasoning, or commentary before or after it:

  "This question is not covered in the provided policy documents.
   For authoritative guidance, please contact:
   • La Trobe University Policy team: policy@latrobe.edu.au
   • Student Services: studentservices@latrobe.edu.au
   • Your faculty's Student Administration office"

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


# Context Formatter

def format_chunks_for_prompt(chunks: list[dict]) -> str:
    """
    Converts Vaidehi's retrieval dict format into a labelled context block.

    Expected chunk fields:
        chunk["content"]         — the policy text
        chunk["document_title"]  — source document name
        chunk["source_url"]      — URL of the policy page
        chunk["chunk_id"]        — unique identifier
        chunk["is_exception"]    — True if this is an exception/override chunk

    NOTE: Headers are kept minimal (no URLs, no IDs) to prevent the LLM
    from copying metadata into its answer. The backend already has full
    metadata in the chunk dicts for citation purposes.
    """
    if not chunks:
        return ""

    formatted = []
    for i, chunk in enumerate(chunks):
        title     = chunk.get("document_title", "Unknown Document")
        is_exc    = chunk.get("is_exception", False)
        content   = chunk.get("content", "")

        label = "[EXCEPTION] " if is_exc else ""
        header = f"[CHUNK {i+1}] {label}{title}"
        formatted.append(f"{header}\n{content}")

    return "\n\n---\n\n".join(formatted)


# ── Kept for backward compatibility with test_generation.py

def format_docs_with_metadata(docs: list) -> str:
    """
    Legacy helper for LangChain Document objects.
    Only used by test_generation.py (Sprint 2 standalone test).
    Do NOT call this from generate_answer().
    """
    if not docs:
        return ""
    formatted = []
    for i, doc in enumerate(docs):
        source_file = doc.metadata.get("source", "Unknown File")
        breadcrumb  = doc.metadata.get("breadcrumb", "General Document")
        page_num    = doc.metadata.get("page", "N/A")
        header = (
            f"[CHUNK {i+1}] SOURCE: {source_file} | "
            f"PAGE: {page_num} | SECTION: {breadcrumb}"
        )
        formatted.append(f"{header}\n{doc.page_content}")
    return "\n\n---\n\n".join(formatted)


#Post-generation Hallucination Validator

FALLBACK_MARKERS = [
    "not covered in the provided policy",
    "this question is not covered",
    "this is not covered in policy",
]

HALLUCINATION_RISK_PHRASES = [
    "typically", "usually", "generally", "often", "in most cases",
    "it is expected", "it is assumed", "should be", "would be",
    "as far as I know", "i believe", "probably", "possibly",
]


def validate_response(answer: str, chunks: list[dict]) -> dict:
    """
    Post-generation grounding check using Vaidehi's dict-format chunks.

    Returns:
      {
        "is_fallback": bool,
        "risk_phrases_found": list[str],
        "keyword_overlap_score": float,
        "flagged": bool,
        "flag_reason": str
      }
    """
    answer_lower = answer.lower()

    is_fallback = any(m in answer_lower for m in FALLBACK_MARKERS)
    if is_fallback:
        return {
            "is_fallback": True,
            "risk_phrases_found": [],
            "keyword_overlap_score": 1.0,
            "flagged": False,
            "flag_reason": "",
        }

    risk_phrases_found = [p for p in HALLUCINATION_RISK_PHRASES if p in answer_lower]

    stopwords = {"the", "a", "an", "is", "are", "was", "were", "in", "of",
                 "to", "and", "or", "for", "with", "on", "at", "by", "be",
                 "it", "this", "that", "as", "not", "no", "if", "from"}

    # Use chunk["content"] from dict format
    context_blob = " ".join(c.get("content", "").lower() for c in chunks)
    context_words = set(context_blob.split()) - stopwords

    answer_words = set(answer_lower.split()) - stopwords
    overlap = len(answer_words & context_words) / len(answer_words) if answer_words else 0.0

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


#  Adversarial Query Detector 

ADVERSARIAL_PATTERNS = [
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


# ── Main guardrail wrapper used by generate_answer

def build_guardrailed_response(query: str, chunks: list[dict], raw_answer: str) -> dict:
    """
    Combines the raw LLM answer with guardrail checks.
    Uses Vaidehi's dict-format chunks (not LangChain Documents).

    Returns the internal validation report — NOT the final backend response.
    The final backend response is built in generate_answer().
    """
    adversarial = is_adversarial(query)
    validation  = validate_response(raw_answer, chunks)
    used_sources = [c.get("chunk_id", "unknown") for c in chunks]

    return {
        "answer": raw_answer,
        "validation": validation,
        "adversarial_warning": adversarial,
        "used_sources": used_sources,
    }


print(f"Prompt Template ({PROMPT_VERSION}) and Guardrails initialised.")
