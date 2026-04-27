from fastapi import APIRouter,Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from models.schemas import ChatRequest, ChatResponse, Citation
from retrieval.retrieve_policies import retrieve_policies
from generation.generate_answer import generate_answer
import json
import time
from datetime import datetime

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


def write_log(log_data: dict):
    with open("request_logs.jsonl", "a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(log_data) + "\n")


@router.post("/ask", response_model=ChatResponse)
@limiter.limit("10/minute")
async def ask_question(request: ChatRequest):
    start_time = time.time()

    try:
        question = request.question
        role = request.role

        # Step 1: Call retrieval and measure retrieval time
        retrieval_start = time.time()
        chunks = retrieve_policies(question, role)
        retrieval_time_ms = round((time.time() - retrieval_start) * 1000, 2)

        # Step 2: Fallback if retrieval returns empty list
        if not chunks:
            final_answer = (
                "I couldn't find any relevant university policies. "
                "Please contact Student Services for further assistance."
            )

            response_time_ms = round((time.time() - start_time) * 1000, 2)

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

        # Step 3: Call generation and measure generation time
        generation_start = time.time()
        generation_result = generate_answer(question, chunks)
        generation_time_ms = round((time.time() - generation_start) * 1000, 2)

        final_answer = generation_result.get(
            "answer",
            "No answer could be generated at this time."
        )

        used_sources = generation_result.get("used_sources", [])

        # Step 4: Map used_sources to retrieval chunks
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
            "retrieved_chunk_count": len(chunks),
            "retrieved_chunk_ids": [chunk.get("chunk_id", "") for chunk in chunks],
            "final_answer": final_answer,
            "is_fallback": False,
            "retrieval_time_ms": retrieval_time_ms,
            "generation_time_ms": generation_time_ms,
            "response_time_ms": response_time_ms
        })

        return ChatResponse(
            answer=final_answer,
            is_fallback=False,
            citations=citations
        )

    except Exception as e:
        final_answer = (
            "Something went wrong while processing your request. "
            "Please try again later or contact Student Services."
        )

        response_time_ms = round((time.time() - start_time) * 1000, 2)

        write_log({
            "timestamp": datetime.now().isoformat(),
            "question": getattr(request, "question", ""),
            "role": getattr(request, "role", ""),
            "retrieved_chunk_count": 0,
            "retrieved_chunk_ids": [],
            "final_answer": final_answer,
            "is_fallback": True,
            "retrieval_time_ms": locals().get("retrieval_time_ms", 0),
            "generation_time_ms": locals().get("generation_time_ms", 0),
            "response_time_ms": response_time_ms,
            "error": str(e)
        })

        return ChatResponse(
            answer=final_answer,
            is_fallback=True,
            citations=[]
        )