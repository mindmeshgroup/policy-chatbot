from langchain_core.prompts import ChatPromptTemplate
RAG_TEMPLATE = """
You are a La Trobe University Policy Assistant. 
Use the Context below to answer the Question.

RULES:
1. Only use the provided Context. 
2. If the answer isn't there, say this is not covered in policy.
3. CITATION RULE: At the very end of your answer, list the Sources and Page Numbers used. 
   Format it as: "Sources: [Filename], Page [Number]".

CONTEXT:
{context}

QUESTION:
{question}

ANSWER:
"""

prompt_template = ChatPromptTemplate.from_template(RAG_TEMPLATE)

#fORMATTING Function
def format_docs_with_metadata(docs):
    if not docs:
        return ""

    formatted_chunks = []
    
    for i, doc in enumerate(docs):
        # Extracting metadata from the 'envelope'
        source_file = doc.metadata.get("source", "Unknown File")
        breadcrumb = doc.metadata.get("breadcrumb", "General Document")
        page_num = doc.metadata.get("page", "N/A")
        audience = doc.metadata.get("audience", "Unknown")
        category = doc.metadata.get("category", "Unknown")
        

        header = f"[CHUNK {i+1}] SOURCE: {source_file} | PAGE: {page_num} | SECTION: {breadcrumb} | AUDIENCE: {audience}"
        
        # Combine Header + Policy Text
        chunk_text = f"{header}\n{doc.page_content}"
        formatted_chunks.append(chunk_text)
    
    return "\n\n".join(formatted_chunks)

print(" Prompt Template and Guardrails initialized.")
