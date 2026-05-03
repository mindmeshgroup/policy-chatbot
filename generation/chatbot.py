import os
from dotenv import load_dotenv

from langchain.vectorstores import Chroma
from langchain.embeddings import HuggingFaceEmbeddings
from langchain.chat_models import ChatOpenAI
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate

from prompt_logic_v3 import (
    RAG_TEMPLATE,
    format_docs_with_metadata,
    build_guardrailed_response,
    PROMPT_VERSION,
)

load_dotenv()

# ── Configuration ───────────────────────────────────────────────────────────────
CHROMA_PATH     = "./chroma_db_vlm"
COLLECTION_NAME = "latrobe_policy_v4"

# ── Initialise components ───────────────────────────────────────────────────────
embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings,
            collection_name=COLLECTION_NAME)
retriever = db.as_retriever(search_kwargs={"k": 5})
llm = ChatOpenAI(model_name="gpt-4o-mini", temperature=0)

QA_PROMPT = PromptTemplate(
    template=RAG_TEMPLATE,
    input_variables=["context", "question"]
)
qa_chain = RetrievalQA.from_chain_type(
    llm=llm,
    chain_type="stuff",
    retriever=retriever,
    return_source_documents=True,
    chain_type_kwargs={"prompt": QA_PROMPT}
)


# ── Public query function ───────────────────────────────────────────────────────

def ask(query: str, verbose: bool = True) -> dict:
    """
    Full RAG pipeline with Sprint 3 guardrails.

    Returns:
      {
        "answer": str,
        "sources": list[str],
        "validation": dict,
        "adversarial_warning": bool,
      }
    """
    raw = qa_chain({"query": query})
    answer      = raw["result"].strip()
    source_docs = raw.get("source_documents", [])

    report = build_guardrailed_response(
        query=query,
        retrieved_docs=source_docs,
        raw_answer=answer,
    )

    if verbose:
        print(f"\n{'═'*65}")
        print(f" CHATBOT ANSWER  [{PROMPT_VERSION}]")
        print(f"{'═'*65}")
        print(answer)

        print(f"\n{'─'*65}")
        print(" SOURCES USED")
        print(f"{'─'*65}")
        for doc in source_docs:
            src     = doc.metadata.get("source", "Unknown")
            section = doc.metadata.get("breadcrumb", "General")
            page    = doc.metadata.get("page", "N/A")
            print(f"  • {src} | Section: {section} | Page: {page}")

        v = report["validation"]
        print(f"\n{'─'*65}")
        print(" GUARDRAIL REPORT")
        print(f"{'─'*65}")
        print(f"  Fallback response    : {v['is_fallback']}")
        print(f"  Keyword overlap      : {v['keyword_overlap_score']:.0%}")
        print(f"  Hallucination flagged: {v['flagged']}")
        if v["flag_reason"]:
            print(f"  Flag reason          : {v['flag_reason']}")
        if report["adversarial_warning"]:
            print("  ⚠️  ADVERSARIAL QUERY DETECTED")

    return report


# ── Demo ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    demo_queries = [
        "What is the academic integrity policy at La Trobe?",
        "Can you help me write my essay?",                                  # out of scope
        "I heard La Trobe allows 30-day late submissions — confirm this?",  # adversarial
    ]
    for q in demo_queries:
        print(f"\n{'█'*65}")
        print(f" QUERY: {q}")
        ask(q, verbose=True)
