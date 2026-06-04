import time
import requests

from retrieval.config import EXTRACTOR_MODEL_NAME, OLLAMA_CHAT_URL
from retrieval.utils.schemas import ExtractedAudience

# -------------------------------------------------------------------------
# LLM audience extraction
# -------------------------------------------------------------------------
def extract_llm_cohort(scouted_text: str, document_title: str, retries: int = 3) -> dict:
    """
    Sends a small document sample to the local LLM and validates its structured
    audience-label response before the result is used as contextual metadata.
    """
    # The model helps preserve detailed audience predictions, while broad
    # operational tags are assigned separately through deterministic rules.
    prompt = f"""
    You classify policy audience metadata for a La Trobe University policy retrieval prototype.
    Return only a JSON object containing the policy title and audience labels supported by explicit evidence in the supplied text.

    1. IDENTIFY TITLE:
    - Extract the official legal name of the policy.
    - Ignore website navigation text such as 'Jump to Content', 'Menu', or 'Search'.
    - If no clear title is present, use: "{document_title}"

    2. IDENTIFY ROLES:
    Select only from this exact list of 12 roles. Do not invent new roles:
    1. "Student": Broad student-related audience.
    2. "Staff": Broad staff-related audience.
    3. "Undergrad": Bachelor, diploma, standard coursework students.
    4. "Postgrad": Master's or advanced coursework students.
    5. "HDR": Higher Degree by Research, PhD, doctoral candidates.
    6. "International": Overseas students, visa holders.
    7. "Academic": Professors, lecturers, tutors, researchers.
    8. "Professional": Admin, IT, HR, management staff.
    9. "Casual": Sessional, hourly, or temporary workers.
    10. "Alumni": Graduates and former students.
    11. "Public": General public, community members.
    12. "Guest": Visitors, contractors, honorary staff.

    RULES:
    - Include ["Student", "Staff", "Public"] only where the text explicitly applies
      to all persons, the whole university community, all staff and students, or
      staff, students and visitors.
    - Do not assign detailed roles unless they are explicitly stated or clearly
      supported by the text.

    Current File Hint: {document_title}
    Text: {scouted_text[:3000]}
    
    Output strictly valid JSON exactly like this: 
    {{"document_title": "Actual Policy Name", "target_cohort": ["Role1", "Role2"]}}
    """
    
    payload = {
        "model": EXTRACTOR_MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "format": ExtractedAudience.model_json_schema(),
        "options": {"temperature": 0.0, "num_ctx": 4096},
        "stream": False
    }

    last_error: Exception | None = None

    # Retry temporary connection or model failures before stopping the document run.
    for attempt in range(retries):
        try:
            response = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=300)
            response.raise_for_status()
            content = response.json()["message"]["content"]
            validated = ExtractedAudience.model_validate_json(content)
            return validated.model_dump()
        except Exception as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(2 ** attempt)

    raise RuntimeError(f"Audience extraction failed for '{document_title}': {last_error}") from last_error