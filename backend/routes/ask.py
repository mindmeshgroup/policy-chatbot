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

# Sprint 5 Task 3: Semantic cache + cache stats
response_cache = {}

cache_stats = {
    "hits": 0,
    "misses": 0
}


def write_log(log_data: dict):
    with open("request_logs.jsonl", "a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(log_data) + "\n")


@router.post("/ask", response_model=ChatResponse)
@limiter.limit("10/minute")
async def ask_question(request: Request, body: ChatRequest):
    start_time = time.time()

    try:
        question = body.question
        role = body.role or "Student"

        if not question or not question.strip():
            return ChatResponse(
                answer="Please enter a valid question.",
                is_fallback=True,
                citations=[]
            )

        cache_key = f"{role}:{question.lower().strip()}"

        # Sprint 5 Task 3: Return cached response if repeated query
        if cache_key in response_cache:
            cache_stats["hits"] += 1
            cached_response = response_cache[cache_key]

            write_log({
                "timestamp": datetime.now().isoformat(),
                "question": question,
                "role": role,
                "cache_hit": True,
                "cache_hits_total": cache_stats["hits"],
                "cache_misses_total": cache_stats["misses"],
                "final_answer": cached_response["answer"],
                "is_fallback": cached_response["is_fallback"],
                "response_time_ms": round((time.time() - start_time) * 1000, 2)
            })

            return ChatResponse(**cached_response)

        cache_stats["misses"] += 1

        # Sprint 4 Task 3: Basic semantic intent guardrail
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
            "refund",
            "fee",
            "appeal",
            "complaint",
            "plagiarism",
            "attendance",
            "course",
            "subject"
        ]

        if not any(keyword in question.lower() for keyword in allowed_keywords):
            final_answer = (
                "Sorry, I can only answer La Trobe University "
                "policy-related questions."
            )

            response_data = {
                "answer": final_answer,
                "is_fallback": True,
                "citations": []
            }

            response_cache[cache_key] = response_data

            write_log({
                "timestamp": datetime.now().isoformat(),
                "question": question,
                "role": role,
                "cache_hit": False,
                "retrieved_chunk_count": 0,
                "retrieved_chunk_ids": [],
                "final_answer": final_answer,
                "is_fallback": True,
                "retrieval_time_ms": 0,
                "generation_time_ms": 0,
                "response_time_ms": round((time.time() - start_time) * 1000, 2)
            })

            return ChatResponse(**response_data)

        # Sprint 4 Task 2: Retrieval integration
        retrieval_start = time.time()
        chunks = await retrieve_policies(question, role)
        retrieval_time_ms = round((time.time() - retrieval_start) * 1000, 2)

        print("FIRST CHUNK:", chunks[0] if chunks else "NO CHUNKS")

        if not chunks:
            final_answer = (
                "I couldn't find any relevant university policies. "
                "Please contact Student Services for further assistance."
            )

            response_data = {
                "answer": final_answer,
                "is_fallback": True,
                "citations": []
            }

            response_cache[cache_key] = response_data

            write_log({
                "timestamp": datetime.now().isoformat(),
                "question": question,
                "role": role,
                "cache_hit": False,
                "retrieved_chunk_count": 0,
                "retrieved_chunk_ids": [],
                "final_answer": final_answer,
                "is_fallback": True,
                "retrieval_time_ms": retrieval_time_ms,
                "generation_time_ms": 0,
                "response_time_ms": round((time.time() - start_time) * 1000, 2)
            })

            return ChatResponse(**response_data)

        # Sprint 4 Task 2: Generation integration
        generation_start = time.time()
        loop = asyncio.get_event_loop()

        generation_result = await loop.run_in_executor(
            None,
            partial(generate_answer, question, chunks)
        )

        print("GENERATION RESULT:", generation_result)

        generation_time_ms = round((time.time() - generation_start) * 1000, 2)

        if isinstance(generation_result, dict):
            final_answer = generation_result.get(
                "answer",
                "No answer could be generated at this time."
            )
            used_sources = generation_result.get("used_sources", [])
        else:
            final_answer = str(generation_result)
            used_sources = []

        print("USED SOURCES:", used_sources)
        print("CHUNK IDS:", [chunk.get("chunk_id") for chunk in chunks])

        # Sprint 4 Task 5: Citation fidelity auditing
        valid_chunk_ids = [chunk.get("chunk_id", "") for chunk in chunks]

        invalid_citations = [
            source for source in used_sources
            if source not in valid_chunk_ids
        ]

        for source in invalid_citations:
            print("INVALID CITATION DETECTED:", source)

        # Sprint 4 Task 5: Citation mapping
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

        response_time_ms = round((time.time() - start_time) * 1000, 2)

        write_log({
            "timestamp": datetime.now().isoformat(),
            "question": question,
            "role": role,
            "cache_hit": False,
            "cache_hits_total": cache_stats["hits"],
            "cache_misses_total": cache_stats["misses"],
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
            "invalid_citations": invalid_citations
        })

        response_data = {
            "answer": final_answer,
            "is_fallback": False,
            "citations": citations
        }

        response_cache[cache_key] = response_data

        return ChatResponse(**response_data)

    except Exception as e:
        final_answer = (
            "Something went wrong while processing your request. "
            "Please try again later or contact Student Services."
        )

        write_log({
            "timestamp": datetime.now().isoformat(),
            "question": getattr(body, "question", ""),
            "role": getattr(body, "role", ""),
            "retrieved_chunk_count": 0,
            "retrieved_chunk_ids": [],
            "final_answer": final_answer,
            "is_fallback": True,
            "retrieval_time_ms": locals().get("retrieval_time_ms", 0),
            "generation_time_ms": locals().get("generation_time_ms", 0),
            "response_time_ms": round((time.time() - start_time) * 1000, 2),
            "error": str(e)
        })

        return ChatResponse(
            answer=final_answer,
            is_fallback=True,
            citations=[]
        )