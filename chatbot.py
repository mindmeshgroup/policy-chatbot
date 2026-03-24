import os
from dotenv import load_dotenv

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_openai import ChatOpenAI
from langchain.chains.retrieval_qa.base import RetrievalQA
from langchain.prompts import PromptTemplate

# -----------------------------
# 1. LOAD API KEY
# -----------------------------
load_dotenv()  # Loads OPENAI_API_KEY from .env

# -----------------------------
# 2. CONNECT TO VAIDEHI'S CHROMA DB
# -----------------------------
CHROMA_PATH = "./chroma_db_vlm"     # Folder from Vaidehi
COLLECTION_NAME = "latrobe_policy_v4"

# Must match Veidehi's embedding model EXACTLY
embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

db = Chroma(
    persist_directory=CHROMA_PATH,
    embedding_function=embeddings,
    collection_name=COLLECTION_NAME
)

# -----------------------------
# 3. RETRIEVER (TOP 5 DOCUMENTS)
# -----------------------------
retriever = db.as_retriever(search_kwargs={"k": 5})

# -----------------------------
# 4. LLM (GPT‑4o‑mini)
# -----------------------------
llm = ChatOpenAI(
    model_name="gpt-4o-mini",
    temperature=0
)

# -----------------------------
# 5. PROMPT TEMPLATE (GROUNDING)
# -----------------------------
template = """
You are the La Trobe University Policy Chatbot.
Use ONLY the following policy context to answer the question.

If the answer is not contained in the context,
respond exactly with: "This is not covered in policy."
Do NOT make up information.

Context:
{context}

Question:
{question}

Helpful Answer:
"""

QA_PROMPT = PromptTemplate(
    template=template,
    input_variables=["context", "question"]
)

# -----------------------------
# 6. BUILD THE RAG CHAIN
# -----------------------------
qa_chain = RetrievalQA.from_chain_type(
    llm=llm,
    chain_type="stuff",
    retriever=retriever,
    return_source_documents=True,
    chain_type_kwargs={"prompt": QA_PROMPT}
)

# -----------------------------
# 7. TEST QUERY
# -----------------------------
query = "What is the policy on academic integrity?"
result = qa_chain.invoke({"query": query})

print("\n--- CHATBOT ANSWER ---")
print(result["result"])

print("\n--- SOURCES USED ---")
for doc in result["source_documents"]:
    source = doc.metadata.get("source", "Unknown Document")
    section = doc.metadata.get("breadcrumb", "General Section")
    print(f"- {source} | Section: {section}")