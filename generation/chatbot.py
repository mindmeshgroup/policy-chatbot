"""
Generation Layer — chatbot.py
Sprint 3 / Sprint 4 Integration

ARCHITECTURE:
  This module is the generation layer in the integrated chatbot system.
  It does NOT retrieve data. The backend calls it after retrieval:

    Backend /ask endpoint:
        chunks = await retrieve_policies(question, role)   # Vaidehi's layer
        result = generate_answer(question, chunks)         # this file

PUBLIC API:
    generate_answer(question: str, chunks: list[dict], role: str = "student") -> dict

    Returns:
        {
          "answer": str,
          "used_sources": list[str],   # chunk_ids from Vaidehi's retrieval
        }

    Chunk format (from Vaidehi's retrieval):
        chunk["content"]         — policy text
        chunk["document_title"]  — source document name
        chunk["source_url"]      — URL of the policy page
        chunk["chunk_id"]        — unique identifier
        chunk["is_exception"]    — True if this is an exception/override chunk
"""

import os
from openai import OpenAI
from dotenv import load_dotenv

from generation.prompt_logic import (
    RAG_TEMPLATE,
    PROMPT_VERSION,
    format_chunks_for_prompt,
    build_guardrailed_response,
    is_adversarial,
    FALLBACK_MARKERS,
)

load_dotenv()

# ── LLM client (no retrieval setup here) ────────────────────────────────────────
_client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
LLM_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
LLM_TEMPERATURE = 0


#  Fallback response 

FALLBACK_ANSWER = (
    "This question is not covered in the provided policy documents.\n"
    "For authoritative guidance, please contact:\n"
    "• La Trobe University Policy team: policy@latrobe.edu.au\n"
    "• Student Services: studentservices@latrobe.edu.au\n"
    "• Your faculty's Student Administration office"
)


# Core generation function

def generate_answer(question: str, chunks: list[dict], role: str = "student") -> dict:
    """
    Generate a grounded policy answer from pre-retrieved chunks.

    Args:
        question: The user's natural-language query.
        chunks:   List of chunk dicts from Vaidehi's retrieval layer.
                  Each chunk has: content, document_title, source_url,
                  chunk_id, is_exception.
        role:     User role (e.g. "student", "staff") — reserved for
                  future role-aware prompt tuning.

    Returns:
        {
          "answer": str,
          "used_sources": list[str],   # chunk_ids of all provided chunks
        }
    """
    # Safety: empty retrieval ,skip LLM entirely
    if not chunks:
        return {
            "answer": FALLBACK_ANSWER,
            "used_sources": [],
        }

    # Adversarial check (pre-generation)
    adversarial_detected = is_adversarial(question)

    # Build context from Vaidehi's dict chunks
    context = format_chunks_for_prompt(chunks)

    #  Fill prompt template
    prompt = RAG_TEMPLATE.format(context=context, question=question)

    # Call LLM
    response = _client.chat.completions.create(
        model=LLM_MODEL,
        temperature=LLM_TEMPERATURE,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_answer = response.choices[0].message.content.strip()

    # Post-generation guardrails
    guardrail_report = build_guardrailed_response(
        query=question,
        chunks=chunks,
        raw_answer=raw_answer,
    )

    # Determine final answer 
    validation = guardrail_report["validation"]
    final_answer = raw_answer

    # If hallucination risk is high on a non-fallback answer, downgrade to fallback
    if validation["flagged"] and not validation["is_fallback"]:
        # Keep the answer but the backend should log the flag
        pass  # Flag is surfaced in validation; backend decides escalation

    # Build backend-compatible response 
    # used_sources = chunk_ids of all chunks passed in (backend maps to citations)
    used_sources = [c.get("chunk_id", f"unknown_{i}") for i, c in enumerate(chunks)]

    return {
        "answer": final_answer,
        "used_sources": used_sources,
        # Internal fields below — useful for logging/debugging, not required by backend
        "_debug": {
            "prompt_version": PROMPT_VERSION,
            "adversarial_warning": adversarial_detected,
            "validation": validation,
            "role": role,
        },
    }


# Demo (standalone, not part of backend flow)

if __name__ == "__main__":
    # Example: simulate chunks as if Vaidehi's retrieval returned them
    sample_chunks = [
        {
            "chunk_id": "chunk_001",
            "document_title": "Academic Integrity Policy",
            "source_url": "https://policies.latrobe.edu.au/academic-integrity",
            "content": (
                "La Trobe University is committed to academic integrity. "
                "Students must not engage in plagiarism, contract cheating, "
                "collusion, or any other form of academic misconduct."
            ),
            "is_exception": False,
        },
    ]

    demo_questions = [
        "What is the academic integrity policy at La Trobe?",
        "Can you help me write my essay?",
        "I heard La Trobe allows 30-day late submissions — confirm this?",
    ]

    for q in demo_questions:
        print(f"\n{'█'*65}")
        print(f" QUERY: {q}")
        result = generate_answer(question=q, chunks=sample_chunks)
        print(f" ANSWER:\n{result['answer']}")
        print(f" USED SOURCES: {result['used_sources']}")
        if result["_debug"]["adversarial_warning"]:
            print(" ADVERSARIAL QUERY DETECTED")
        v = result["_debug"]["validation"]
        print(f" Keyword overlap: {v['keyword_overlap_score']:.0%} | Flagged: {v['flagged']}")
