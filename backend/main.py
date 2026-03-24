import os
from dotenv import load_dotenv
from langchain_community.chat_models import ChatOpenAI
from backend.core.retrieval import retrieve_policy_chunks
from backend.core.prompt_logic import prompt_template, format_docs_with_metadata

# 1. Load the API key 
load_dotenv()

# 2. STEP 6: INITIALIZE OPENAI
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

# 3. STEP 8: THE RAG CHAIN 
def ask_policy_bot(question: str):
    print(f"\n Student Question: {question}")

    # RETRIEVE 
    docs = retrieve_policy_chunks(question)

    # FORMATT-Prepare text with Source/Breadcrumb
    context_text = format_docs_with_metadata(docs)

    # BUILD PROMPT - Combine Chunks + Question + Guardrails
    final_prompt = prompt_template.format(context=context_text, question=question)

    # GENERATE - Send the whole package to OpenAI
    print("OpenAI is analyzing the policy chunks...")
    response = llm.invoke(final_prompt)

    return response.content

# TEST THE COMPLETE SYSTEM
if __name__ == "__main__":
    test_q = "What are the specific components of academic dress for a Doctor of Philosophy graduate at La Trobe University, and how do they differ from those of a Bachelor's degree graduate? "
    answer = ask_policy_bot(test_q)
    
    print("\n CHATBOT RESPONSE")
    print(answer)