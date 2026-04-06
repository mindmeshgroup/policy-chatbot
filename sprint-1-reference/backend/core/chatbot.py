import os
from dotenv import load_dotenv

from langchain.vectorstores import Chroma
from langchain.embeddings import HuggingFaceEmbeddings
from langchain.chat_models import ChatOpenAI
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate


load_dotenv() 


CHROMA_PATH = "./chroma_db_vlm"     
COLLECTION_NAME = "latrobe_policy_v4"


embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

db = Chroma(
    persist_directory=CHROMA_PATH,
    embedding_function=embeddings,
    collection_name=COLLECTION_NAME
)

retriever = db.as_retriever(search_kwargs={"k": 5})

llm = ChatOpenAI(
    model_name="gpt-4o-mini",
    temperature=0
)

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

qa_chain = RetrievalQA.from_chain_type(
    llm=llm,
    chain_type="stuff",
    retriever=retriever,
    return_source_documents=True,
    chain_type_kwargs={"prompt": QA_PROMPT}
)


query = "What are the specific components of academic dress for a Doctor of Philosophy graduate at La Trobe University, and how do they differ from those of a Bachelor's degree graduate? "
result = qa_chain({"query": query})

print("\n CHATBOT ANSWER")
print(result["result"])

print("\n SOURCES USED")
for doc in result["source_documents"]:
    source = doc.metadata.get("source", "Unknown Document")
    section = doc.metadata.get("breadcrumb", "General Section")
    print(f"- {source} | Section: {section}")