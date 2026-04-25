def generate_answer(question: str, chunks: list):
    return {
        "answer": "Based on the retrieved university policies, here is the relevant information for your query.",
        "used_sources": [chunk["chunk_id"] for chunk in chunks[:2]]
    }