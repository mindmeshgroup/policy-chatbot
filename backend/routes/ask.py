from fastapi import APIRouter, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from models.schemas import ChatRequest, ChatResponse, Citation
from retrieval.retrieve_policies import retrieve_policies
import time

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

@router.post("/ask", response_model=ChatResponse)
@limiter.limit("10/minute")
async def ask_question(request: Request, payload: ChatRequest):
    try:
        question = payload.question
        role = payload.role

        # Step 1: Call retrieval (with the 'await' fix)
        chunks = await retrieve_policies(question, role)
        
        # Step 2: Print to terminal so you can verify it worked
        print(f"\n SUCCESSFULLY RETRIEVED {len(chunks)} CHUNKS!")
        print(chunks)
        
        # Step 3: Fallback if empty
        if not chunks:
            return ChatResponse(
                answer="I couldn't find any relevant university policies.",
                is_fallback=True,
                citations=[]
            )

        # Step 4: Testing Bypass (Skips the missing Generation layer)
        final_answer = f"TESTING MODE: Backend successfully retrieved {len(chunks)} chunks! Check your VS Code terminal."
        
        citations = []
        for chunk in chunks:
            citations.append(
                Citation(
                    title=chunk.get("document_title", "Document"),
                    url=chunk.get("source_url", ""),
                    breadcrumb=chunk.get("breadcrumb", ""),
                    escalation_contact=chunk.get("escalation_contact", "Student Services"),
                    excerpt=chunk.get("content", "")[:200]
                )
            )

        return ChatResponse(
            answer=final_answer,
            is_fallback=False,
            citations=citations
        )

    except Exception as e:
        print(f"\n FATAL ERROR: {str(e)}")
        return ChatResponse(
            answer=f"Testing Error: {str(e)}",
            is_fallback=True,
            citations=[]
        )