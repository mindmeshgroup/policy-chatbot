import asyncio
import json
import os
from typing import Any

from ollama import AsyncClient


# Local model used to rewrite policy questions and identify requests that are
# clearly outside the purpose of the policy retrieval prototype.
REWRITER_MODEL_NAME = os.getenv(
    "QUERY_REWRITER_MODEL_NAME",
    "qwen2.5:3b",
)

# These detailed audience labels may be recorded as context hints only.
# Active retrieval access is still controlled separately by Student, Staff or Public.
ALLOWED_CONTEXTUAL_HINTS = {
    "Undergrad",
    "Postgrad",
    "HDR",
    "International",
    "Academic",
    "Professional",
    "Casual",
    "Alumni",
    "Guest",
}


def _clean_contextual_hints(raw_hints: Any) -> list[str]:
    """Keeps only detailed audience hints supported by the metadata taxonomy."""
    if not isinstance(raw_hints, list):
        return []

    return sorted({
        str(hint).strip()
        for hint in raw_hints
        if str(hint).strip() in ALLOWED_CONTEXTUAL_HINTS
    })


def _read_boolean(value: Any, default: bool = True) -> bool:
    """
    Reads the scope-classification value safely from the model response.

    An unclear value defaults to True so a potentially valid policy question is
    not blocked only because the local model returned malformed JSON content.
    """
    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        normalised_value = value.strip().casefold()

        if normalised_value == "true":
            return True

        if normalised_value == "false":
            return False

    return default


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    """Checks whether any expected policy term occurs in lower-case query text."""
    return any(term in text for term in terms)


def _apply_policy_term_corrections(
    raw_query: str,
    technical_query: str,
    step_back_query: str,
) -> tuple[str, str]:
    """
    Preserves policy concepts that the local rewriter confused during testing.

    This is not a replacement for semantic rewriting. It is a small safeguard
    for clear domain terms where an incorrect paraphrase can direct retrieval
    towards the wrong policy document.
    """
    lowered_query = raw_query.casefold()

    # In this policy library, Personal Work and paid outside work are part of
    # Outside Work rules, not leave entitlements.
    if _contains_any(
        lowered_query,
        ("personal work", "side hustle", "freelance", "outside work"),
    ):
        technical_query = (
            "Outside Work Policy requirements for Personal Work, "
            "paid external work caps and required approval"
        )
        step_back_query = (
            "Rules governing Outside Work or Personal Work undertaken "
            "by university staff"
        )

    # Falsifying or fabricating research-related data is a research-integrity
    # issue. This prevents the word 'data' from incorrectly biasing retrieval
    # towards privacy-breach procedures.
    if (
        _contains_any(
            lowered_query,
            ("falsif", "fabricat", "manipulat"),
        )
        and _contains_any(
            lowered_query,
            ("research", "grant", "academic", "data"),
        )
    ):
        technical_query = (
            "Research Integrity Policy consequences for research misconduct "
            "involving fabrication or falsification of research or grant data"
        )
        step_back_query = (
            "Research misconduct and breaches of research integrity involving "
            "fabrication or falsification of data"
        )

    # Authorship order and first-author questions belong to authorship policy,
    # rather than general thesis or intellectual-property publication rules.
    if _contains_any(
        lowered_query,
        ("first author", "authorship", "co-author", "coauthor"),
    ):
        technical_query = (
            "Research Authorship and Outputs Policy requirements for "
            "authorship eligibility and author order"
        )
        step_back_query = (
            "Attribution of authorship and resolution of author-order matters "
            "in research outputs"
        )

    # Grade appeal / unfair marking questions map to the Assessment Procedure
    # for formal review and re-mark, not misconduct appeals.
    if _contains_any(
        lowered_query,
        ("appeal my grade", "appeal a grade", "appeal the grade",
         "grade appeal", "unfair mark", "unfairly marked",
         "remark", "re-mark", "formal review", "review my mark",
         "contest my grade", "challenge my grade", "dispute my mark"),
    ):
        technical_query = (
            "Assessment Procedure formal review re-mark student request "
            "unfair marking rubric not followed subject coordinator"
        )
        step_back_query = (
            "Student rights to request a formal review or re-mark of an "
            "assessment task under the Assessment Procedure"
        )

    # Plagiarism / academic misconduct questions map to the Student Academic
    # Misconduct Policy, not general integrity statements.
    if _contains_any(
        lowered_query,
        ("plagiari", "academic misconduct", "academic integrity",
         "cheating", "contract cheat", "collusion"),
    ):
        technical_query = (
            "Student Academic Misconduct Policy plagiarism cheating "
            "consequences penalties investigation procedure"
        )
        step_back_query = (
            "Student obligations and penalties under the academic integrity "
            "and misconduct policy at La Trobe University"
        )

    # Special consideration questions — distinguish from staff special leave.
    if _contains_any(
        lowered_query,
        ("special consideration", "special con", "apply for consideration",
         "extension for assessment", "extenuating circumstances"),
    ):
        technical_query = (
            "Special Consideration Procedure student application assessment "
            "short extension eligibility submission deadline"
        )
        step_back_query = (
            "Student application process and eligibility for special "
            "consideration or short extension due to extenuating circumstances"
        )

    return technical_query, step_back_query


async def rewrite_query(raw_query: str, user_role: str) -> dict:
    """
    Rewrites a question and decides whether policy retrieval is appropriate.

    user_role is part of the retrieval-service interface, but it is deliberately
    not sent to the model. The trusted role filter in retrieve_policies.py
    controls access independently from LLM-generated search wording.
    """
    _ = user_role
    client = AsyncClient()

    system_prompt = """
    You support retrieval from La Trobe University policy and procedure documents.

    First determine whether the user's question requires retrieval from a
    university policy knowledge base.

    Set "requires_policy_retrieval" to true only when the question concerns a
    university policy, procedure, rule, obligation, entitlement, approval,
    appeal, breach, privacy matter, employment matter, student matter,
    research requirement, records-management requirement, safety requirement,
    or a contact responsible for one of these matters.

    Set "requires_policy_retrieval" to false for greetings, casual
    conversation, food recommendations, entertainment recommendations,
    general knowledge requests or requests clearly unrelated to university
    rules and procedures.

    When policy retrieval is required, produce:
    1. "Cleaned": correct spelling and grammar while preserving meaning.
    2. "Technical": express the same question using likely policy terminology.
    3. "Step-Back": state the broader policy concept behind the question.

    Important terminology rules:
    - Preserve important policy terms from the original question.
    - "Personal work", "side hustle" or "freelance gig" in an employment
      context relates to Outside Work or Personal Work, not personal leave.
    - "Falsifying", "fabricating" or "manipulating" research or grant data
      relates to research integrity or research misconduct, not privacy breach
      response, unless the question explicitly concerns disclosure, access to
      personal information or privacy.
    - "First author", "author order" or "authorship" relates to research
      authorship and outputs.
    - Do not insert audience labels or account roles into Cleaned, Technical
      or Step-Back. Never prefix text with Student, Staff, Undergrad,
      Postgrad, HDR, Academic or Professional.
    - Only when an audience is explicitly stated by the user, it may be
      returned separately under "contextual_audience_hints".
    - Detailed audience hints may be selected only from:
      "Undergrad", "Postgrad", "HDR", "International", "Academic",
      "Professional", "Casual", "Alumni", "Guest".
    - Audience hints are contextual metadata only. They never determine access.

    Output strictly valid JSON in exactly this structure:
    {
      "requires_policy_retrieval": true,
      "Cleaned": "...",
      "Technical": "...",
      "Step-Back": "...",
      "contextual_audience_hints": []
    }
    """

    try:
        response = await client.chat(
            model=REWRITER_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"User Query: {raw_query!r}"},
            ],
            format="json",
            options={"temperature": 0.0},
            keep_alive="5m",
        )

        rewritten_data = json.loads(response["message"]["content"])

        requires_retrieval = _read_boolean(
            rewritten_data.get("requires_policy_retrieval"),
            default=True,
        )

        cleaned_query = str(
            rewritten_data.get("Cleaned", raw_query)
        ).strip() or raw_query

        technical_query = str(
            rewritten_data.get("Technical", raw_query)
        ).strip() or raw_query

        step_back_query = str(
            rewritten_data.get("Step-Back", raw_query)
        ).strip() or raw_query

        technical_query, step_back_query = _apply_policy_term_corrections(
            raw_query=raw_query,
            technical_query=technical_query,
            step_back_query=step_back_query,
        )

        return {
            "requires_policy_retrieval": requires_retrieval,
            "cleaned_query": cleaned_query,
            "technical_query": technical_query,
            "step_back_query": step_back_query,
            "contextual_audience_hints": _clean_contextual_hints(
                rewritten_data.get("contextual_audience_hints", [])
            ),
        }

    except Exception as exc:
        print(f"[!] Ollama query rewriter error: {exc}")

        # Retrieval remains possible if rewriting fails. The original wording
        # is retained, and active role filtering remains enforced elsewhere.
        return {
            "requires_policy_retrieval": True,
            "cleaned_query": raw_query,
            "technical_query": raw_query,
            "step_back_query": raw_query,
            "contextual_audience_hints": [],
        }


if __name__ == "__main__":
    manual_checks = [
        "What is the maximum number of days for paid personal work?",
        "can i start a side hustle or freelance gig if I work here full time?",
        "as a phd student, who gets to be the first author on my thesis paper?",
        "what happens if an academic gets caught falsifying their grant data?",
        "Where can I find a good pepperoni pizza?",
    ]

    for query in manual_checks:
        result = asyncio.run(
            rewrite_query(query, "Staff")
        )

        print(f"\nQuery: {query}")
        print(json.dumps(result, indent=2))
