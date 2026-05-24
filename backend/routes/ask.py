
from fastapi import APIRouter, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from backend.models.schemas import ChatRequest, ChatResponse, Citation
from retrieval.retrieve_policies import retrieve_policies
from generation.chatbot import generate_answer

import asyncio
import json
import time
from datetime import datetime
from functools import partial

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

# =========================================================
# TASK 4: Semantic Caching
# Stores repeated questions to reduce retrieval/generation
# calls and improve response time.
# =========================================================
cache = {}


def write_log(log_data: dict):
    """
    TASK 2: Debug & Stabilise Integration Issues

    Logs request/response data for debugging,
    monitoring integration flow, and identifying
    runtime errors during testing.
    """

    with open("request_logs.jsonl", "a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(log_data) + "\n")


@router.post("/ask", response_model=ChatResponse)
@limiter.limit("10/minute")
async def ask_question(request: Request, body: ChatRequest):

    # =========================================================
    # TASK 2: Backend Integration Monitoring
    # Measures total API response time for debugging
    # and performance validation.
    # =========================================================
    start_time = time.time()

    try:
        question = body.question

        # =========================================================
        # TASK 2: Integration Stability Improvement
        # Default role fallback prevents NoneType errors
        # when frontend does not send a role.
        # =========================================================
        role = body.role or "Student"

        # =========================================================
        # TASK 2: Input Validation
        # Prevents empty questions from reaching retrieval
        # or generation layers.
        # =========================================================
        if not question.strip():
            return ChatResponse(
                answer="Please enter a valid question.",
                is_fallback=True,
                citations=[]
            )

        # =========================================================
        # TASK 4: Semantic Cache Key
        # Normalises user queries before caching.
        # =========================================================
        cache_key = question.lower().strip()

        # =========================================================
        # TASK 4: Cached Response Return
        # Returns stored response immediately if query
        # has already been processed before.
        # =========================================================
        if cache_key in cache:
            return cache[cache_key]

        # =========================================================
        # TASK 3: Semantic Intent Guardrails
        # Blocks non-policy or irrelevant questions before
        # retrieval is triggered.
        # =========================================================
        allowed_keywords = [
            "policy",
            "student",
            "assessment",
            "extension",
            "academic",
            "misconduct",
            "privacy",
            "enrolment",
            "exam",
            "leave",
            "university",
            "special consideration",
            "appeal",
            "grade",
            "fee",
            "credit",
            "withdrawal",
            "result",
            "complaint",
            "rights",
            "scholarship",
            "refund",
            "course",
            "subject",
            "unit",
            "degree",
            "graduation",
            "defer",
            "suspend",
            "penalty",
            "plagiarism",
        ]

        if not any(keyword in question.lower() for keyword in allowed_keywords):
            return ChatResponse(
                answer="Sorry, I can only answer La Trobe University policy-related questions.",
                is_fallback=True,
                citations=[]
            )

        # =========================================================
        # TASK 2: Retrieval Integration Timing
        # Measures retrieval performance and validates
        # retrieval integration.
        # =========================================================
        retrieval_start = time.time()

        chunks = await retrieve_policies(question, role)

        retrieval_time_ms = round(
            (time.time() - retrieval_start) * 1000,
            2
        )

        # =========================================================
        # TASK 2: Retrieval Debugging
        # Prints retrieval output structure to help identify
        # metadata mismatches and integration issues.
        # =========================================================
        print("FIRST CHUNK:", chunks[0] if chunks else "NO CHUNKS")

        # =========================================================
        # TASK 2: Retrieval Fallback Handling
        # Returns safe response if retrieval fails to
        # return relevant policy chunks.
        # =========================================================
        if not chunks:

            final_answer = (
                "I couldn't find any relevant university policies. "
                "Please contact Student Services for further assistance."
            )

            response_time_ms = round(
                (time.time() - start_time) * 1000,
                2
            )

            write_log({
                "timestamp": datetime.now().isoformat(),
                "question": question,
                "role": role,
                "retrieved_chunk_count": 0,
                "retrieved_chunk_ids": [],
                "final_answer": final_answer,
                "is_fallback": True,
                "retrieval_time_ms": retrieval_time_ms,
                "generation_time_ms": 0,
                "response_time_ms": response_time_ms
            })

            return ChatResponse(
                answer=final_answer,
                is_fallback=True,
                citations=[]
            )

        # =========================================================
        # TASK 2: Generation Layer Integration
        # Runs blocking generation code safely in a thread
        # without blocking the FastAPI event loop.
        # =========================================================
        generation_start = time.time()

        loop = asyncio.get_event_loop()

        generation_result = await loop.run_in_executor(
            None,
            partial(generate_answer, question, chunks)
        )

        # =========================================================
        # TASK 2: Generation Output Debugging
        # Prints generation response structure to detect
        # format mismatches between backend and generation.
        # =========================================================
        print("GENERATION RESULT:", generation_result)

        generation_time_ms = round(
            (time.time() - generation_start) * 1000,
            2
        )

        # =========================================================
        # TASK 2: Safe Generation Handling
        # Prevents crashes if generation layer returns
        # unexpected formats.
        # =========================================================
        if isinstance(generation_result, dict):

            final_answer = generation_result.get(
                "answer",
                "No answer could be generated at this time."
            )

            used_sources = generation_result.get(
                "used_sources",
                []
            )

        else:
            final_answer = str(generation_result)
            used_sources = []

        print("USED SOURCES:", used_sources)

        print(
            "CHUNK IDS:",
            [chunk.get("chunk_id") for chunk in chunks]
        )

        # =========================================================
        # TASK 5: Citation Fidelity Auditing
        # Validates whether generation citations match
        # retrieval chunk metadata.
        # =========================================================
        valid_chunk_ids = [
            chunk.get("chunk_id", "")
            for chunk in chunks
        ]

        for source in used_sources:
            if source not in valid_chunk_ids:
                print("INVALID CITATION DETECTED:", source)

        # =========================================================
        # TASK 5: Citation Mapping
        # Maps generation citations back to retrieval
        # metadata for frontend display.
        # =========================================================
        citations = []

        for chunk in chunks:

            chunk_id = chunk.get("chunk_id", "")

            if chunk_id in used_sources:

                citations.append(
                    Citation(
                        title=chunk.get("document_title", ""),
                        url=chunk.get("source_url", ""),
                        breadcrumb=chunk.get("breadcrumb", ""),
                        escalation_contact=chunk.get(
                            "escalation_contact",
                            "Student Services"
                        ),
                        excerpt=chunk.get("content", "")[:200]
                    )
                )

        response_time_ms = round(
            (time.time() - start_time) * 1000,
            2
        )

        # =========================================================
        # TASK 2 & TASK 5: Logging and Validation
        # Logs integration data, timings, chunk IDs,
        # and invalid citation information for debugging.
        # =========================================================
        write_log({
            "timestamp": datetime.now().isoformat(),
            "question": question,
            "role": role,
            "retrieved_chunk_count": len(chunks),
            "retrieved_chunk_ids": [
                chunk.get("chunk_id", "")
                for chunk in chunks
            ],
            "final_answer": final_answer,
            "is_fallback": False,
            "retrieval_time_ms": retrieval_time_ms,
            "generation_time_ms": generation_time_ms,
            "response_time_ms": response_time_ms,
            "invalid_citations": [
                source for source in used_sources
                if source not in valid_chunk_ids
            ]
        })

        # =========================================================
        # Final API Response
        # =========================================================
        response = ChatResponse(
            answer=final_answer,
            is_fallback=False,
            citations=citations
        )

        # =========================================================
        # TASK 4: Cache Storage
        # Saves successful responses into semantic cache.
        # =========================================================
        cache[cache_key] = response

        return response

    except Exception as e:

        # =========================================================
        # TASK 2: Global Exception Handling
        # Prevents API crashes and ensures stable fallback
        # responses during unexpected runtime errors.
        # =========================================================
        final_answer = (
            "Something went wrong while processing your request. "
            "Please try again later or contact Student Services."
        )

        response_time_ms = round(
            (time.time() - start_time) * 1000,
            2
        )

        write_log({
            "timestamp": datetime.now().isoformat(),
            "question": getattr(body, "question", ""),
            "role": getattr(body, "role", ""),
            "retrieved_chunk_count": 0,
            "retrieved_chunk_ids": [],
            "final_answer": final_answer,
            "is_fallback": True,
            "retrieval_time_ms": locals().get(
                "retrieval_time_ms",
                0
            ),
            "generation_time_ms": locals().get(
                "generation_time_ms",
                0
            ),
            "response_time_ms": response_time_ms,
            "error": str(e)
        })

        return ChatResponse(
            answer=final_answer,
            is_fallback=True,
            citations=[]
        )

