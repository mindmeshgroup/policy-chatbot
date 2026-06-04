import asyncio
import csv
import json
import time
from pathlib import Path

from retrieval.retrieve_policies import retrieve_policies


# -------------------------------------------------------------------------
# Evaluation configuration
# -------------------------------------------------------------------------

# The evaluation checks whether the expected policy appears among the first
# five distinct retrieved policy documents.
DOCUMENT_K = 5

# More chunks are requested than the document-level K because several returned
# chunks may belong to the same policy document.
RETRIEVAL_CHUNK_LIMIT = 10

# Store evidence outputs in a dedicated folder beside this script.
OUTPUT_DIR = Path(__file__).resolve().parent / "evaluation_outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

JSON_OUTPUT_PATH = OUTPUT_DIR / "retrieval_metrics_results_15_queries.json"
CSV_OUTPUT_PATH = OUTPUT_DIR / "retrieval_metrics_results_15_queries.csv"


# -------------------------------------------------------------------------
# Matched evaluation dataset for the promoted 20-policy collection
# -------------------------------------------------------------------------

# Each expected policy below is present in the promoted 20-policy candidate.
# The Research Integrity query is deliberately retained as a known difficult
# case rather than removed to make the results look better.
GOLDEN_DATASET = [
    {
        "query": "How quickly must I report a privacy data breach?",
        "expected_title": "Privacy Policy",
        "role": "Student",
    },
    {
        "query": "Do students own the intellectual property they create?",
        "expected_title": "Intellectual Property Policy",
        "role": "Student",
    },
    {
        "query": "What is the maximum number of days for paid personal work?",
        "expected_title": "Outside Work Policy (Academic)",
        "role": "Staff",
    },
    {
        "query": "What does the Records Management Policy require for university records?",
        "expected_title": "Records Management Policy",
        "role": "Staff",
    },
    {
        "query": "I was terminated from my employment. What process applies?",
        "expected_title": "Termination of Employment Procedure",
        "role": "Staff",
    },
    {
        "query": "Can a research contract delay the publication of research findings?",
        "expected_title": "Research Contracts and Grants Policy",
        "role": "Staff",
    },
    {
        "query": "As a PhD student, who qualifies for authorship on a research output?",
        "expected_title": "Research Authorship and Outputs Policy",
        "role": "Student",
    },
    {
        "query": "What are researchers required to do with research data?",
        "expected_title": "Research Data Management Policy",
        "role": "Staff",
    },
    {
        "query": "What happens if an academic falsifies research or grant data?",
        "expected_title": "Research Integrity Policy",
        "role": "Staff",
    },
    {
        "query": "What approvals are required before conducting research involving biological hazards?",
        "expected_title": "Research Biosafety and Biosecurity Procedure",
        "role": "Staff",
    },
    {
        "query": "Do I need ethics approval before using animals in research?",
        "expected_title": "Research Animal Ethics Procedure",
        "role": "Staff",
    },
    {
        "query": "How is an allegation of research misconduct handled?",
        "expected_title": "Research Misconduct Procedure",
        "role": "Staff",
    },
    {
        "query": "What procedure applies if a graduate research student is accused of research misconduct?",
        "expected_title": "Research - Higher Degree Student Misconduct Procedure",
        "role": "Student",
    },
    {
        "query": "Do I need human ethics approval before conducting research with human participants?",
        "expected_title": "Research Human Ethics Procedure",
        "role": "Staff",
    },
    {
        "query": "What are the requirements for submitting a graduate research thesis for examination?",
        "expected_title": (
            "Graduate Research Examinations Procedure - "
            "Thesis Requirements, Submission and Retention"
        ),
        "role": "Student",
    },
]


# -------------------------------------------------------------------------
# Title matching and document-level ranking helpers
# -------------------------------------------------------------------------

def normalise_title(title: str) -> str:
    """
    Normalises title spacing and letter case while preserving document identity.
    """
    return " ".join(str(title).casefold().split())


def title_matches_expected(retrieved_title: str, expected_title: str) -> bool:
    """
    Checks whether a retrieved document title is the expected indexed title.

    Exact normalised title matching is used because this evaluation dataset was
    constructed only from policies confirmed to exist in the current database.
    """
    return normalise_title(retrieved_title) == normalise_title(expected_title)


def get_unique_document_results(response: list[dict]) -> list[dict]:
    """
    Keeps only the first retrieved chunk from each distinct policy document.

    Retrieval returns chunks, but this evaluation measures document retrieval.
    Without this step, multiple chunks from one policy could unfairly push a
    relevant second policy below the evaluation cut-off.
    """
    unique_results: list[dict] = []
    seen_titles: set[str] = set()

    for result in response:
        title = result.get("document_title", "Unknown Document")
        title_key = normalise_title(title)

        if title_key in seen_titles:
            continue

        seen_titles.add(title_key)
        unique_results.append(result)

    return unique_results


# -------------------------------------------------------------------------
# Evaluation execution
# -------------------------------------------------------------------------

async def run_evaluation() -> None:
    """
    Runs document-level retrieval evaluation on the promoted 20-policy database.
    """
    print("\n" + "=" * 72)
    print("RETRIEVAL METRICS TEST - 15 MATCHED QUERIES")
    print("=" * 72)
    print(
          "Database scope: promoted full public-policy collection "
    "(214 accessible policies; 5,479 validated chunks)"    )
    print(f"Document-level Recall@K: K = {DOCUMENT_K}")
    print(f"Retrieved chunks requested per query: {RETRIEVAL_CHUNK_LIMIT}")
    print(
        "Known difficult case retained: research-integrity falsification query\n"
    )

    results: list[dict] = []
    reciprocal_ranks: list[float] = []

    top_one_correct_count = 0
    recall_at_k_count = 0
    total_start_time = time.time()

    for index, item in enumerate(GOLDEN_DATASET, start=1):
        query_start_time = time.time()

        print(f"[{index}/{len(GOLDEN_DATASET)}] Query: {item['query']}")
        print(f"    Expected: {item['expected_title']}")
        print(f"    Role: {item['role']}")

        response = await retrieve_policies(
            item["query"],
            role=item["role"],
            max_k=RETRIEVAL_CHUNK_LIMIT,
        )

        unique_document_results = get_unique_document_results(response)
        top_k_results = unique_document_results[:DOCUMENT_K]

        retrieved_top_titles = [
            result.get("document_title", "Unknown Document")
            for result in top_k_results
        ]

        top_result_title = (
            unique_document_results[0].get(
                "document_title",
                "Unknown Document",
            )
            if unique_document_results
            else "No result"
        )

        top_result_score = (
            unique_document_results[0].get("score")
            if unique_document_results
            else None
        )

        expected_rank = 0
        expected_document_score = None

        for rank, result in enumerate(top_k_results, start=1):
            retrieved_title = result.get(
                "document_title",
                "Unknown Document",
            )

            if title_matches_expected(
                retrieved_title,
                item["expected_title"],
            ):
                expected_rank = rank
                expected_document_score = result.get("score")
                break

        retrieved_at_k = expected_rank > 0
        top_one_correct = expected_rank == 1
        reciprocal_rank = (
            1.0 / expected_rank
            if expected_rank > 0
            else 0.0
        )

        elapsed_seconds = time.time() - query_start_time

        if retrieved_at_k:
            recall_at_k_count += 1

        if top_one_correct:
            top_one_correct_count += 1

        reciprocal_ranks.append(reciprocal_rank)

        result_record = {
            "query": item["query"],
            "role": item["role"],
            "expected_title": item["expected_title"],
            "top_result_title": top_result_title,
            "top_result_score": top_result_score,
            "retrieved_top_titles": retrieved_top_titles,
            "expected_document_rank_within_top_k": expected_rank,
            "expected_document_score": expected_document_score,
            "retrieved_at_k": retrieved_at_k,
            "top_one_correct": top_one_correct,
            "reciprocal_rank": round(reciprocal_rank, 4),
            "elapsed_seconds": round(elapsed_seconds, 2),
        }

        results.append(result_record)

        if top_one_correct:
            print(
                f"    PASS: Correct policy ranked first "
                f"(score={top_result_score}).\n"
            )
        elif retrieved_at_k:
            print(
                f"    PARTIAL: Expected policy retrieved at document rank "
                f"{expected_rank} within top {DOCUMENT_K}.\n"
            )
        else:
            print(
                f"    FAIL: Expected policy not retrieved within top "
                f"{DOCUMENT_K}. Retrieved: {retrieved_top_titles}\n"
            )

    total_queries = len(GOLDEN_DATASET)
    total_execution_seconds = time.time() - total_start_time

    top_one_accuracy = (
        top_one_correct_count / total_queries
        if total_queries else 0.0
    )

    recall_at_k = (
        recall_at_k_count / total_queries
        if total_queries else 0.0
    )

    mean_reciprocal_rank = (
        sum(reciprocal_ranks) / total_queries
        if total_queries else 0.0
    )


    summary = {
        "database_scope": "Promoted 20-policy publication-test collection",
        "queries_tested": total_queries,
        "document_k": DOCUMENT_K,
        "retrieval_chunk_limit": RETRIEVAL_CHUNK_LIMIT,
        "top_1_document_accuracy": round(top_one_accuracy, 4),
        "recall_at_k": round(recall_at_k, 4),
        "mean_reciprocal_rank": round(mean_reciprocal_rank, 4),
        "total_execution_seconds": round(total_execution_seconds, 2),
        "known_difficult_query": (
            "What happens if an academic falsifies research or grant data?"
        ),
        "evaluation_note": (
            "This evaluation measures document-level retrieval against "
            "15 expected policy titles selected from the promoted "
            "20-policy collection."
        ),
        "results": results,
    }

    with open(JSON_OUTPUT_PATH, "w", encoding="utf-8") as json_file:
        json.dump(summary, json_file, indent=2)

    with open(CSV_OUTPUT_PATH, "w", newline="", encoding="utf-8") as csv_file:
        fieldnames = [
            "query",
            "role",
            "expected_title",
            "top_result_title",
            "top_result_score",
            "retrieved_top_titles",
            "expected_document_rank_within_top_k",
            "expected_document_score",
            "retrieved_at_k",
            "top_one_correct",
            "reciprocal_rank",
            "elapsed_seconds",
        ]

        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()

        for result in results:
            csv_row = dict(result)
            csv_row["retrieved_top_titles"] = " | ".join(
                result["retrieved_top_titles"]
            )
            writer.writerow(csv_row)

    failed_recall_results = [
        result
        for result in results
        if not result["retrieved_at_k"]
    ]

    incorrect_top_one_results = [
        result
        for result in results
        if not result["top_one_correct"]
    ]

    print("\n" + "=" * 72)
    print("RETRIEVAL QUALITY CONTROL REPORT")
    print("=" * 72)
    print(f"Total Queries Tested       : {total_queries}")
    print(f"Execution Time             : {total_execution_seconds:.2f} seconds")
    print(f"Top-1 Document Accuracy    : {top_one_accuracy * 100:.2f}%")
    print(f"Recall@{DOCUMENT_K}                 : {recall_at_k * 100:.2f}%")
    print(f"Mean Reciprocal Rank       : {mean_reciprocal_rank:.4f}")

    if incorrect_top_one_results:
        print("\nTOP-RANKING ERRORS OR LOWER-RANKED CORRECT DOCUMENTS")
        print("-" * 72)

        for result in incorrect_top_one_results:
            print(f"Query        : {result['query']}")
            print(f"Expected     : {result['expected_title']}")
            print(f"Top Retrieved: {result['top_result_title']}")
            print(
                "Expected Rank : "
                f"{result['expected_document_rank_within_top_k'] or 'Not in top K'}"
            )
            print()

    if failed_recall_results:
        print(f"FAILED RETRIEVALS OUTSIDE TOP {DOCUMENT_K}")
        print("-" * 72)

        for result in failed_recall_results:
            print(f"Query    : {result['query']}")
            print(f"Expected : {result['expected_title']}")
            print(f"Retrieved: {result['retrieved_top_titles']}")
            print()
    else:
        print(
            f"\nAll expected documents were retrieved within top {DOCUMENT_K}."
        )

    print(f"\nJSON evidence saved to: {JSON_OUTPUT_PATH}")
    print(f"CSV evidence saved to : {CSV_OUTPUT_PATH}")
    print("=" * 72)


if __name__ == "__main__":
    asyncio.run(run_evaluation())