import re
from retrieval.utils.schemas import CONTEXTUAL_AUDIENCE_TAGS

# -------------------------------------------------------------------------
# Text matching and breadcrumb helpers
# -------------------------------------------------------------------------
def _contains_term(text: str, terms: list[str]) -> bool:
    """Checks whether any audience term appears as a complete word or phrase."""
    return any(re.search(rf"\b{re.escape(term)}\b", text) for term in terms)

# -------------------------------------------------------------------------
# Audience tagging rules
# -------------------------------------------------------------------------
ALL_ROLES = [
    "Student",
    "Staff",
    "Undergrad",
    "Postgrad",
    "HDR",
    "International",
    "Academic",
    "Professional",
    "Casual",
    "Alumni",
    "Public",
    "Guest",
]
# Match model outputs to the standard spelling used in saved metadata.
ROLE_LOOKUP = {role.casefold(): role for role in ALL_ROLES}

# Terms that clearly indicate student-related content. The generic word
# "learner" is excluded because policies may refer to a learner driver's permit.
STUDENT_TERMS = [
    "student",
    "students",
    "student candidate",
    "research candidate",
    "admission",
    "enrolment",
    "enrollment",
    "coursework",
    "exam",
    "assessment",
    "scholarship",
    "undergraduate",
    "undergrad",
    "postgraduate",
    "master's",
    "masters",
    "hdr",
    "doctoral",
    "phd",
    "higher degree by research",
    "international student",
    "overseas student",
    "student visa",
]

# Terms that indicate staff or employee-related policy content.
STAFF_TERMS = [
    "staff",
    "employee",
    "employees",
    "employment",
    "workplace",
    "recruitment",
    "salary",
    "overtime",
    "academic staff",
    "professional staff",
    "administrative staff",
    "casual staff",
    "sessional staff",
    "lecturer",
    "examiner",
    "course coordinator",
]

# Phrases that show the content relates to external or public audiences.
PUBLIC_PHRASES = [
    "general public",
    "members of the public",
    "community members",
    "visitors",
]

# These phrases explicitly show that a rule applies across broad user groups.
UNIVERSAL_PHRASES = [
    "all persons",
    "all members of the university community",
    "all staff and students",
    "staff, students and visitors",
    "everyone at the university",
]

def _normalise_roles(raw_roles: list) -> set[str]:
    """Keeps supported audience labels and restores their standard spelling."""
    normalised = set()
    for role in raw_roles:
        supported_role = ROLE_LOOKUP.get(str(role).strip().casefold())
        if supported_role:
            normalised.add(supported_role)
    return normalised

def _get_base_primary_cohorts(
    scouted_context: str,
    document_title: str,
) -> list[str]:
    """
    Identifies the broad document-level audience tags used by active retrieval.

    These tags are assigned through deterministic checks rather than relying
    directly on the experimental LLM audience predictions.
    """
    text_to_scan = f"{document_title} {scouted_context}".casefold()
    primary_cohorts = set()

    if _contains_term(text_to_scan, STUDENT_TERMS):
        primary_cohorts.add("Student")
    if _contains_term(text_to_scan, STAFF_TERMS):
        primary_cohorts.add("Staff")
    if any(phrase in text_to_scan for phrase in PUBLIC_PHRASES):
        primary_cohorts.add("Public")
    if any(phrase in text_to_scan for phrase in UNIVERSAL_PHRASES):
        primary_cohorts.update({"Student", "Staff", "Public"})

    return sorted(primary_cohorts)

def _get_base_contextual_tags(
    scouted_context: str,
    document_title: str,
    llm_roles: list,
) -> list[str]:
    """
    Retains detailed audience predictions as experimental metadata.

    These tags preserve the earlier granular classification work but are not
    used by the current active retrieval filter.
    """
    cohort_raw = llm_roles if isinstance(llm_roles, list) else [llm_roles]

    # Store only the supported detailed labels in the experimental metadata field.
    final_set = _normalise_roles(cohort_raw).intersection(CONTEXTUAL_AUDIENCE_TAGS)
    text_to_scan = (document_title + " " + scouted_context).casefold()
    title_lower = document_title.casefold()

    if _contains_term(text_to_scan, ["undergraduate", "undergrad"]):
        final_set.add("Undergrad")
    if _contains_term(text_to_scan, ["postgraduate", "masters", "master's"]):
        final_set.add("Postgrad")
    if _contains_term(text_to_scan, ["hdr", "doctoral", "phd", "research degree", "graduate research"]):
        final_set.add("HDR")
    if _contains_term(text_to_scan, ["international student", "overseas student", "student visa"]):
        final_set.add("International")
    if _contains_term(text_to_scan, ["academic staff", "lecturer", "examiner", "supervisor", "course coordinator"]):
        final_set.add("Academic")
    if _contains_term(text_to_scan, ["professional staff", "administrative staff"]):
        final_set.add("Professional")
    if _contains_term(text_to_scan, ["casual staff", "sessional staff"]):
        final_set.add("Casual")

    # Remove detailed student labels from documents whose title clearly
    # describes an employment or staff-management policy.
    HR_TITLES = [
        "employment", "termination of employment", "remuneration",
        "staff leave", "staff workload", "staff probation",
        "performance review", "flexible working", "working from home",
        "staff recruitment", "outside work", "conflict of interest"
    ]
    if any(k in title_lower for k in HR_TITLES):
        final_set.difference_update(["Undergrad", "Postgrad", "HDR", "International", "Alumni", "Guest"])
    if any(k in title_lower for k in ["graduate", "postgraduate", "hdr", "doctoral", "masters", "higher degree", "research degree"]):
        final_set.difference_update(["Undergrad", "Alumni", "Guest"])
    if "undergraduate" in title_lower:
        final_set.difference_update(["Postgrad", "HDR"])

    return list(final_set)

