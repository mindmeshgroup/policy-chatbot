import json
import asyncio
from ollama import AsyncClient

# Using the optimal local model identified in your research
REWRITER_MODEL = "qwen2.5:3b"

async def rewrite_query(raw_query: str, user_role: str) -> dict:
    """
    Takes a raw user query and uses a local Ollama model to generate multiple 
    optimized search variants and extract implicit filters before querying Qdrant.
    Now fully ASYNCHRONOUS.
    """
    client = AsyncClient()
    
    system_prompt = """
    You are an expert Policy Librarian at La Trobe University. 
    Your job is to take a messy, colloquial user query and rewrite it into highly effective search queries for a vector database.
    
    1. Provide a "Cleaned" version (fix typos).
    2. Provide a "Technical" version (translate slang into official university policy jargon, like 'Special Consideration' instead of 'sick note').
    3. Provide a "Step-Back" version (a broader, abstract concept query).
    
    You must also determine if the query implies a specific target cohort (Undergrad, Postgrad, HDR, Academic, Professional, Public). 
    If not, return an empty list for implicit_filters.

    Output strictly valid JSON exactly like this:
    {
      "Cleaned": "...",
      "Technical": "...",
      "Step-Back": "...",
      "implicit_filters": ["Role1", "Role2"]
    }
    """

    user_prompt = f"User Query: '{raw_query}'\nUser Account Role: {user_role}"

    try:
        response = await client.chat(
            model=REWRITER_MODEL, 
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt}
            ], 
            format='json', 
            options={'temperature': 0.0},
            keep_alive="5m"
        )
        
        rewritten_data = json.loads(response['message']['content'])
        
        return {
            "cleaned_query": rewritten_data.get("Cleaned", raw_query),
            "technical_query": rewritten_data.get("Technical", raw_query),
            "step_back_query": rewritten_data.get("Step-Back", raw_query),
            "implicit_filters": rewritten_data.get("implicit_filters", [])
        }
        
    except Exception as e:
        print(f"[!] Ollama Query Rewriter Error: {e}")
        return {
            "cleaned_query": raw_query,
            "technical_query": raw_query,
            "step_back_query": raw_query,
            "implicit_filters": []
        }

# --- Quick Local Test ---
if __name__ == "__main__":
    test_query = "can i get an extnsion on my essay if im super sick?"
    print(f"Testing local Ollama model: {REWRITER_MODEL}...")
    print(f"Raw Query: {test_query}\n")
    
    result = asyncio.run(rewrite_query(test_query, "Student"))
    print(json.dumps(result, indent=2))