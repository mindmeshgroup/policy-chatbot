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
        return value.strip()

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if not value or not value.strip():
            return "Student"
        return value.strip()


class Citation(BaseModel):
    title: str
    url: str
    breadcrumb: str
    escalation_contact: str
    excerpt: str


class ChatResponse(BaseModel):
    answer: str
    is_fallback: bool
    citations: List[Citation]