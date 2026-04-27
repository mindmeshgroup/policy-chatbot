from pydantic import BaseModel, Field, field_validator
from typing import List


class ChatRequest(BaseModel):
    question: str = Field(..., max_length=500)
    role: str = "Student"

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Question must not be empty")

        cleaned = value.strip()

        blocked_patterns = ["<script", "</script", "DROP TABLE", "DELETE FROM"]

        for pattern in blocked_patterns:
            if pattern.lower() in cleaned.lower():
                raise ValueError("Question contains invalid content")

        return cleaned

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        allowed_roles = ["Student", "Staff"]

        if value not in allowed_roles:
            return "Student"

        return value


class Citation(BaseModel):
    title: str = ""
    url: str = ""
    breadcrumb: str = ""
    escalation_contact: str = ""
    excerpt: str = ""


class ChatResponse(BaseModel):
    answer: str
    is_fallback: bool
    citations: List[Citation]