from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, field_validator

# Broad audience tags used by the current role-aware retrieval filter.
PRIMARY_COHORTS = {
    "Student",
    "Staff",
    "Public",
}

# Detailed audience tags retained for future validation and refinement.
CONTEXTUAL_AUDIENCE_TAGS = {
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

class ExtractedAudience(BaseModel):
    """Validates the structured audience response returned by the local LLM."""
    document_title: str
    target_cohort: List[str]

class ContactDict(BaseModel):
    """Stores contact information extracted from the policy metadata."""
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None

class PolicyChunkPayload(BaseModel):
    """Defines the validated metadata stored with each policy chunk."""
    model_config = ConfigDict(extra="forbid")

    content: str
    has_table: bool
    is_exception: bool
    document_title: str
    source_url: str
    enquiries_contact: ContactDict
    responsible_manager: ContactDict
    escalation_contact: str
    breadcrumb: str
    document_summary: str
    doc_type: str
    category: str
    access_level: str

    # Broad labels used by the current retrieval filter.
    target_cohort: List[str]

    # Detailed labels retained as experimental metadata.
    contextual_audience_tags: List[str]

    campus_scope: List[str]
    document_id: str

    # Groups HTML and PDF versions that represent the same policy.
    canonical_document_id: str

    approval_body: Optional[str] = None
    department_owner: ContactDict
    status: Optional[str] = None
    effective_date_iso: Optional[str] = None
    review_date: Optional[str] = None
    chunk_id: str
    chunk_index: int
    chunk_type: str
    chunking_method: str

    @field_validator("target_cohort")
    @classmethod
    def validate_primary_cohorts(cls, values: List[str]) -> List[str]:
        if not values:
            raise ValueError("At least one broad audience tag is required for retrieval filtering.")
        invalid_values = set(values) - PRIMARY_COHORTS
        if invalid_values:
            raise ValueError(f"Only Student, Staff or Public may be used in target_cohort: {sorted(invalid_values)}")
        return sorted(set(values))

    @field_validator("contextual_audience_tags")
    @classmethod
    def validate_contextual_audience_tags(cls, values: List[str]) -> List[str]:
        invalid_values = set(values) - CONTEXTUAL_AUDIENCE_TAGS
        if invalid_values:
            raise ValueError(f"Unsupported contextual audience tags: {sorted(invalid_values)}")
        return sorted(set(values))