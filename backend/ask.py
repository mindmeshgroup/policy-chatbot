from fastapi import APIRouter
from models.schemas import ChatRequest, ChatResponse, Citation
from retrieval.retrieve_policies import retrieve_policies
from generation.generate_answer import generate_answer
import json
import time
from datetime import datetime
from slowapi import Limiter
from slowapi.util import get_remote_address
limiter = Limiter(key_func=get_remote_address)
router = APIRouter()


def write_log(log_data: dict):
    with open("request_logs.jsonl", "a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(log_data) + "\n")



@router.post("/ask", response_model=ChatResponse)
@limiter.limit("5/minute")
async def ask_question(request: ChatRequest):
    start_time = time.time()

    try:
        question = request.question
        role = request.role

        # Step 1: call retrieval
        chunks = retrieve_policies(question, role)

        # Step 2: fallback if retrieval returns empty list
        if not chunks:
            final_answer = (
                "I couldn't find any relevant university policies. "
                "Please contact Student Services for further assistance."
            )
            response_time_ms = round((time.time() - start_time) * 1000, 2)

            write_log({
                "timestamp": datetime.now().isoformat(),
                "question": question,
                "retrieved_chunk_count": 0,
                "final_answer": final_answer,
                "response_time_ms": response_time_ms
            })

            return ChatResponse(
                answer=final_answer,
                is_fallback=True,
                citations=[]
            )

        # Step 3: call generation
        generation_result = generate_answer(question, chunks)
        used_sources = generation_result.get("used_sources", [])

        # Step 4: map generation used_sources back to retrieval chunk_ids
        citations = []
        for chunk in chunks:
            chunk_id = getattr(chunk, "chunk_id", "")
            metadata = getattr(chunk, "metadata", {})
            content = getattr(chunk, "page_content", "")

            title = metadata.get("document_title", metadata.get("source", ""))
            url = metadata.get("source_url", metadata.get("url", ""))
            breadcrumb = metadata.get("breadcrumb", "")
            escalation_contact = metadata.get("escalation_contact", "Student Services")

            if not used_sources or chunk_id in used_sources:
                citations.append(
                    Citation(
                        title=title,
                        url=url,
                        breadcrumb=breadcrumb,
                        escalation_contact=escalation_contact,
                        excerpt=content[:200]
                    )
                )

        # Step 5: final answer
        final_answer = generation_result.get(
            "answer",
            "No answer could be generated at this time."
        )
        response_time_ms = round((time.time() - start_time) * 1000, 2)

        write_log({
            "timestamp": datetime.now().isoformat(),
            "question": question,
            "retrieved_chunk_count": len(chunks),
            "final_answer": final_answer,
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
            "retrieved_chunk_count": 0,
            "final_answer": final_answer,
            "response_time_ms": response_time_ms,
            "error": str(e)
        })

        return ChatResponse(
            answer=final_answer,
            is_fallback=True,
            citations=[]
        )