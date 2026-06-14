import asyncio
import datetime
import hashlib
import json
import multiprocessing
import os
import shutil
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path
from typing import Callable

import aiohttp
from crawl4ai import AsyncWebCrawler

from retrieval.config import WEB_HUB_URL
from retrieval.setup_db import create_candidate_collection
from retrieval.utils.alias_manager import promote_candidate_collection
from retrieval.utils.crawler import process_single_url, scout_policy_links
from retrieval.utils.state_manager import get_all_states, save_states

# -------------------------------------------------------------------------
# Orchestration limits and checkpoint storage
# -------------------------------------------------------------------------

# Limit simultaneous page requests so a full-library run does not send too
# many requests to the public policy site at once.
MAX_WEB_STAGE_CONCURRENCY = int(
    os.getenv("MAX_WEB_STAGE_CONCURRENCY", "7")
)

# Reject a candidate build when a policy remains stuck inside one stage for
# longer than this duration.
DOCUMENT_PROCESS_TIMEOUT_SECONDS = int(
    os.getenv("DOCUMENT_PROCESS_TIMEOUT_SECONDS", "900")
)

# Parsing is memory-heavy because workers may load Docling dependencies.
MAX_CPU_WORKER_CAP = int(
    os.getenv("MAX_CPU_WORKER_CAP", "3")
)

# Chunking remains parallel but runs separately from later Ollama-heavy stages.
MAX_CHUNKING_WORKERS = int(
    os.getenv("MAX_CHUNKING_WORKERS", "2")
)

# Metadata validation can process two documents concurrently. If local Ollama
# remains unstable after increasing ai_client timeout, reduce this to one.
MAX_VALIDATION_WORKERS = int(
    os.getenv("MAX_VALIDATION_WORKERS", "2")
)

# Final vector insertion remains a controlled parallel indexing stage.
MAX_INSERTION_WORKERS = int(
    os.getenv("MAX_INSERTION_WORKERS", "2")
)

# Number of policies used by the end-to-end publication-path test.
PIPELINE_TEST_DOCUMENT_LIMIT = int(
    os.getenv("PIPELINE_TEST_DOCUMENT_LIMIT", "10")
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = PROJECT_ROOT / "data" / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

# Completed worker results update the same checkpoint file frequently during
# parallel processing. This lock ensures one in-process manifest write is
# completed before another replacement begins.
_MANIFEST_WRITE_LOCK = threading.Lock()

# Windows can temporarily deny an atomic replacement when the file is briefly
# locked by filesystem activity or security scanning. Retry rather than fail
# the entire ingestion build because of a short-lived checkpoint write issue.
_MANIFEST_WRITE_RETRIES = int(
    os.getenv("MANIFEST_WRITE_RETRIES", "8")
)

STAGES = (
    "staged",
    "parsed",
    "chunked",
    "validated",
    "inserted",
)

PATH_FIELDS = {
    "staged": "file_path",
    "parsed": "parsed_path",
    "chunked": "chunked_path",
    "validated": "validated_path",
}


# -------------------------------------------------------------------------
# Checkpoint manifest helpers
# -------------------------------------------------------------------------

def utc_timestamp() -> str:
    """Creates a readable UTC timestamp for checkpointed run identifiers."""
    return datetime.datetime.now(
        datetime.timezone.utc
    ).strftime("%Y%m%d_%H%M%S_%f")


def manifest_path(run_id: str) -> Path:
    """Returns the manifest path for one checkpointed ingestion run."""
    return RUNS_DIR / run_id / "manifest.json"


def save_manifest(manifest: dict) -> None:
    """
    Persists one checkpoint manifest using a Windows-safe atomic write.

    During a parallel stage, completed document results are recorded frequently.
    A unique temporary filename prevents collisions with a previous temporary
    manifest, while retrying os.replace handles short Windows file-lock events
    without cancelling the complete ingestion run.
    """
    path = manifest_path(manifest["run_id"])
    path.parent.mkdir(parents=True, exist_ok=True)

    last_error: Exception | None = None

    with _MANIFEST_WRITE_LOCK:
        for attempt in range(1, _MANIFEST_WRITE_RETRIES + 1):
            temporary_path = path.with_name(
                f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
            )

            try:
                with open(temporary_path, "w", encoding="utf-8") as file:
                    json.dump(manifest, file, indent=2)
                    file.flush()
                    os.fsync(file.fileno())

                # Atomic publication of a fully written checkpoint file.
                os.replace(temporary_path, path)
                return

            except PermissionError as exc:
                last_error = exc

                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

                if attempt < _MANIFEST_WRITE_RETRIES:
                    delay_seconds = 0.25 * attempt
                    print(
                        "[WARN] Windows temporarily locked the checkpoint "
                        f"manifest. Retrying save in {delay_seconds:.2f} seconds..."
                    )
                    time.sleep(delay_seconds)
                    continue

                raise RuntimeError(
                    "Checkpoint manifest could not be saved after repeated "
                    "Windows file-lock retries."
                ) from exc

            except Exception:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
                raise

    raise RuntimeError(
        f"Checkpoint manifest could not be saved: {last_error}"
    )


def load_manifest(path: Path) -> dict:
    """Loads a previously checkpointed ingestion run."""
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def checkpoint_artifact(
    manifest: dict,
    stage: str,
    source_path: str,
    source_url: str,
) -> str:
    """
    Copies one completed intermediate output into this run's checkpoint folder.

    The processing utilities also save outputs in their normal data folders.
    Keeping a run-specific copy prevents a later new build from overwriting the
    files needed to resume this unpublished candidate.
    """
    original_path = Path(source_path)

    if not original_path.exists():
        raise FileNotFoundError(
            f"Cannot checkpoint missing {stage} output: {original_path}"
        )

    document_key = hashlib.sha256(
        source_url.encode("utf-8")
    ).hexdigest()[:12]

    stage_directory = (
        manifest_path(manifest["run_id"]).parent
        / "artifacts"
        / stage
    )
    stage_directory.mkdir(parents=True, exist_ok=True)

    saved_path = stage_directory / f"{document_key}_{original_path.name}"
    shutil.copy2(original_path, saved_path)

    return str(saved_path)


def create_manifest(
    selected_links: list[str],
    mode: str,
) -> dict:
    """
    Creates a new manifest for a rebuild or publication-path test.

    The candidate collection is recorded later, once all documents have passed
    validation and vector insertion is ready to begin.
    """
    run_id = f"run_{utc_timestamp()}"

    manifest = {
        "run_id": run_id,
        "mode": mode,
        "created_at_utc": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "status": "created",
        "candidate_collection": None,
        "alias_promoted": False,
        "ledger_updated": False,
        "promoted": False,
        "documents": {
            url: {
                "url": url,
                "title": url,
                "content_hash": None,
                "is_updated": True,
                "restricted": False,
                "stages": {
                    stage: "pending"
                    for stage in STAGES
                },
                "error": None,
            }
            for url in selected_links
        },
    }

    save_manifest(manifest)
    return manifest


def find_latest_incomplete_manifest() -> dict | None:
    """
    Returns the most recently modified unpublished run manifest, if one exists.
    """
    candidates = []

    for path in RUNS_DIR.glob("*/manifest.json"):
        try:
            manifest = load_manifest(path)
        except (OSError, json.JSONDecodeError):
            continue

        if not manifest.get("promoted", False):
            candidates.append(
                (path.stat().st_mtime, manifest)
            )

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    return candidates[0][1]


def reset_from_stage(document: dict, failed_stage: str) -> None:
    """
    Resets one document from a missing or invalid checkpoint output onward.
    """
    start_index = STAGES.index(failed_stage)

    for stage in STAGES[start_index:]:
        document["stages"][stage] = "pending"

        path_field = PATH_FIELDS.get(stage)
        if path_field:
            document.pop(path_field, None)

    document["error"] = (
        f"Saved checkpoint output for '{failed_stage}' was unavailable; "
        "the document will be regenerated from this stage."
    )


def repair_missing_checkpoint_files(manifest: dict) -> None:
    """
    Invalidates a completed stage when its saved intermediate file no longer exists.
    """
    repaired = False

    for document in manifest["documents"].values():
        if document.get("restricted"):
            continue

        for stage in ("staged", "parsed", "chunked", "validated"):
            if document["stages"].get(stage) != "success":
                break

            saved_path = document.get(PATH_FIELDS[stage])

            if not saved_path or not Path(saved_path).exists():
                reset_from_stage(document, stage)
                repaired = True
                break

    if repaired:
        manifest["status"] = "checkpoint_repaired"
        save_manifest(manifest)


def accessible_documents(manifest: dict) -> list[dict]:
    """Returns documents that should proceed through ingestion and indexing."""
    return [
        document
        for document in manifest["documents"].values()
        if not document.get("restricted", False)
    ]


def restricted_documents(manifest: dict) -> list[dict]:
    """Returns authenticated pages deliberately excluded from public indexing."""
    return [
        document
        for document in manifest["documents"].values()
        if document.get("restricted", False)
    ]


def stage_complete_for_accessible_documents(
    manifest: dict,
    stage: str,
) -> bool:
    """Checks whether every accessible policy completed the required stage."""
    documents = accessible_documents(manifest)

    return bool(documents) and all(
        document["stages"].get(stage) == "success"
        for document in documents
    )


def stage_failures(
    manifest: dict,
    stage: str,
) -> list[dict]:
    """Returns failures recorded for one processing stage."""
    failures = []

    for document in accessible_documents(manifest):
        if document["stages"].get(stage) == "failed":
            failures.append({
                "status": "failed",
                "stage": stage,
                "url": document["url"],
                "title": document.get("title", document["url"]),
                "error": document.get("error", "Unknown error"),
            })

    return failures


def inserted_results_from_manifest(manifest: dict) -> list[dict]:
    """Builds reporting results from documents already inserted successfully."""
    return [
        {
            "url": document["url"],
            "title": document.get("title", document["url"]),
            "content_hash": document.get("content_hash"),
            "chunk_count": document.get("chunk_count", 0),
            "chunking_methods": document.get("chunking_methods", {}),
        }
        for document in accessible_documents(manifest)
        if document["stages"].get("inserted") == "success"
    ]


def restricted_results_from_manifest(manifest: dict) -> list[dict]:
    """Builds ledger/reporting records for intentionally excluded restricted pages."""
    return [
        {
            "url": document["url"],
            "title": document.get("title", document["url"]),
            "hash": document.get("content_hash"),
            "content_hash": document.get("content_hash"),
            "is_updated": document.get("is_updated", True),
        }
        for document in restricted_documents(manifest)
    ]


def changed_count_from_manifest(manifest: dict) -> int:
    """Counts staged or restricted policy pages that changed since publication."""
    return sum(
        1
        for document in manifest["documents"].values()
        if document.get("is_updated", True)
    )


# -------------------------------------------------------------------------
# Worker sizing and stage workers
# -------------------------------------------------------------------------

def calculate_safe_workers() -> int:
    """Selects a conservative base worker count from local CPU and RAM."""
    try:
        import psutil

        detected_ram_gb = psutil.virtual_memory().total / (1024 ** 3)
    except ImportError:
        detected_ram_gb = 16.0

    available_ram_gb = float(
        os.getenv("INGESTION_AVAILABLE_RAM_GB", str(detected_ram_gb))
    )

    memory_limited_workers = max(
        1,
        int((available_ram_gb - 6) / 4),
    )

    return max(
        1,
        min(
            max(1, multiprocessing.cpu_count() - 1),
            memory_limited_workers,
            MAX_CPU_WORKER_CAP,
        ),
    )


def parse_staged_policy(capsule: dict) -> dict:
    """Parses one saved HTML policy and returns its structured JSON path."""
    from retrieval.utils.parser import parse_and_save

    title = capsule.get("title", capsule["url"])

    try:
        parsed_path = parse_and_save(capsule["file_path"])

        return {
            **capsule,
            "status": "success",
            "parsed_path": parsed_path,
        }

    except Exception as exc:
        return {
            "status": "failed",
            "stage": "parsed",
            "url": capsule["url"],
            "title": title,
            "error": str(exc),
        }


def chunk_parsed_policy(parsed_result: dict) -> dict:
    """
    Applies semantic retrieval chunking to one parsed policy document.

    Chunking-time embeddings locate semantic boundaries; these are separate
    from the final dense and sparse vectors later stored in Qdrant.
    """
    from retrieval.utils.chunker import apply_semantic_chunking

    title = parsed_result.get("title", parsed_result["url"])

    try:
        chunked_path = apply_semantic_chunking(
            parsed_result["parsed_path"]
        )

        return {
            **parsed_result,
            "status": "success",
            "chunked_path": chunked_path,
        }

    except Exception as exc:
        return {
            "status": "failed",
            "stage": "chunked",
            "url": parsed_result["url"],
            "title": title,
            "error": str(exc),
        }


def validate_chunked_policy(chunked_result: dict) -> dict:
    """Validates and tags one chunked document before database insertion."""
    from retrieval.utils.payload_builder import validate_and_tag_document

    title = chunked_result.get("title", chunked_result["url"])

    try:
        validated_path = validate_and_tag_document(
            chunked_result["chunked_path"]
        )

        with open(validated_path, "r", encoding="utf-8") as file:
            validated_data = json.load(file)

        chunks = validated_data.get("chunks", [])

        if not chunks:
            raise RuntimeError("No validated chunks were produced.")

        method_counts = Counter(
            chunk.get("chunking_method", "Unknown")
            for chunk in chunks
        )

        return {
            **chunked_result,
            "status": "success",
            "validated_path": validated_path,
            "chunk_count": len(chunks),
            "chunking_methods": dict(method_counts),
        }

    except Exception as exc:
        return {
            "status": "failed",
            "stage": "validated",
            "url": chunked_result["url"],
            "title": title,
            "error": str(exc),
        }


def insert_validated_policy(task: dict) -> dict:
    """
    Generates final hybrid vectors and inserts one validated policy document.

    Multiple policies may be inserted concurrently. Each insertion worker limits
    dense embedding calls within its document to one request at a time.
    """
    from retrieval.utils.vector_engine import clean_and_upsert

    validated_result = task["validated_result"]
    candidate_collection = task["candidate_collection"]
    title = validated_result.get("title", validated_result["url"])

    try:
        with open(
            validated_result["validated_path"],
            "r",
            encoding="utf-8",
        ) as file:
            validated_data = json.load(file)

        chunks = validated_data.get("chunks", [])

        if not chunks:
            raise RuntimeError("No validated chunks were available for insertion.")

        clean_and_upsert(
            collection_name=candidate_collection,
            payloads=chunks,
            max_dense_workers=1,
        )

        return {
            **validated_result,
            "status": "success",
        }

    except Exception as exc:
        return {
            "status": "failed",
            "stage": "inserted",
            "url": validated_result["url"],
            "title": title,
            "error": str(exc),
        }


def run_stage_with_timeout(
    inputs: list[dict],
    worker_function: Callable[[dict], dict],
    stage_name: str,
    max_workers: int,
    record_result: Callable[[dict], None],
) -> tuple[list[dict], list[dict]]:
    """
    Runs one processing stage with controlled workers and immediate checkpointing.

    Only enough tasks to fill available workers are submitted at once. Timeout
    measurement therefore reflects assigned processing time rather than time
    spent waiting behind earlier documents.
    """
    if not inputs:
        return [], []

    successful_results: list[dict] = []
    failures: list[dict] = []
    queued_inputs = iter(inputs)
    timeout_detected = False
    executor = ProcessPoolExecutor(max_workers=max_workers)
    future_to_input: dict = {}
    pending: set = set()

    def submit_next():
        try:
            item = next(queued_inputs)
        except StopIteration:
            return None

        future = executor.submit(worker_function, item)
        future_to_input[future] = {
            "item": item,
            "submitted_at": time.monotonic(),
        }
        return future

    for _ in range(min(max_workers, len(inputs))):
        future = submit_next()
        if future is not None:
            pending.add(future)

    try:
        while pending:
            completed, still_pending = wait(
                pending,
                timeout=1,
                return_when=FIRST_COMPLETED,
            )
            pending = set(still_pending)

            for future in completed:
                item = future_to_input[future]["item"]

                try:
                    result = future.result()
                except Exception as exc:
                    result = {
                        "status": "failed",
                        "stage": stage_name,
                        "url": item.get("url", "Unknown source"),
                        "title": item.get("title", item.get("url", "Unknown source")),
                        "error": str(exc),
                    }

                record_result(result)

                if result["status"] == "success":
                    successful_results.append(result)
                else:
                    failures.append(result)

                next_future = submit_next()
                if next_future is not None:
                    pending.add(next_future)

            now = time.monotonic()
            timed_out_futures = [
                future
                for future in pending
                if now - future_to_input[future]["submitted_at"]
                > DOCUMENT_PROCESS_TIMEOUT_SECONDS
            ]

            if timed_out_futures:
                timeout_detected = True

                for future in timed_out_futures:
                    item = future_to_input[future]["item"]

                    if "validated_result" in item:
                        timed_out_item = item["validated_result"]
                    else:
                        timed_out_item = item

                    timeout_result = {
                        "status": "failed",
                        "stage": stage_name,
                        "url": timed_out_item.get("url", "Unknown source"),
                        "title": timed_out_item.get(
                            "title",
                            timed_out_item.get("url", "Unknown source"),
                        ),
                        "error": (
                            f"Document exceeded {DOCUMENT_PROCESS_TIMEOUT_SECONDS} "
                            f"seconds during {stage_name}."
                        ),
                    }

                    record_result(timeout_result)
                    failures.append(timeout_result)
                    future.cancel()
                    pending.discard(future)

                for future in pending:
                    future.cancel()

                break

    finally:
        executor.shutdown(
            wait=not timeout_detected,
            cancel_futures=timeout_detected,
        )

    return successful_results, failures


# -------------------------------------------------------------------------
# HTML staging and per-stage checkpoint updates
# -------------------------------------------------------------------------

async def stage_pending_html(
    manifest: dict,
    ledger: dict[str, str],
) -> None:
    """Stages only policy pages not already saved successfully in this run."""
    pending_urls = [
        document["url"]
        for document in manifest["documents"].values()
        if document["stages"].get("staged") != "success"
        and not document.get("restricted", False)
    ]

    if not pending_urls:
        print("[*] HTML staging checkpoint found; no pages need to be redownloaded.")
        return

    fetch_semaphore = asyncio.Semaphore(MAX_WEB_STAGE_CONCURRENCY)

    async with AsyncWebCrawler(verbose=False) as crawler:
        async with aiohttp.ClientSession() as session:

            async def bounded_stage(url: str) -> tuple[str, dict]:
                async with fetch_semaphore:
                    try:
                        result = await process_single_url(
                            url=url,
                            crawler=crawler,
                            session=session,
                            ledger=ledger,
                        )
                        return url, result
                    except Exception as exc:
                        return url, {
                            "status": "failed",
                            "url": url,
                            "title": url,
                            "error": str(exc),
                        }

            tasks = [
                asyncio.create_task(bounded_stage(url))
                for url in pending_urls
            ]

            for task in asyncio.as_completed(tasks):
                url, result = await task
                document = manifest["documents"][url]

                if result.get("status") == "restricted":
                    document.update({
                        "title": result.get("title", url),
                        "content_hash": result.get(
                            "content_hash",
                            result.get("hash"),
                        ),
                        "is_updated": result.get("is_updated", True),
                        "restricted": True,
                        "error": None,
                    })
                    document["stages"]["staged"] = "restricted"

                    for later_stage in ("parsed", "chunked", "validated", "inserted"):
                        document["stages"][later_stage] = "not_required"

                    print(f"   [RESTRICTED] Authentication required: {url}")

                elif result.get("status") == "failed":
                    document["stages"]["staged"] = "failed"
                    document["error"] = result.get("error", "Unknown web staging error")
                    print(f"   [FETCH FAILED] {url}: {document['error']}")

                else:
                    document.update({
                        "title": result.get("title", url),
                        "content_hash": result.get("content_hash"),
                        "is_updated": result.get("is_updated", True),
                        "file_path": checkpoint_artifact(
                            manifest,
                            "raw_html",
                            result["file_path"],
                            url,
                        ),
                        "restricted": False,
                        "error": None,
                    })
                    document["stages"]["staged"] = "success"

                save_manifest(manifest)


def record_parsing_result(manifest: dict, result: dict) -> None:
    """Writes the parsing outcome of one policy into the run checkpoint."""
    document = manifest["documents"][result["url"]]

    if result["status"] == "success":
        document.update({
            "title": result.get("title", document["title"]),
            "parsed_path": checkpoint_artifact(
                manifest,
                "parsed",
                result["parsed_path"],
                result["url"],
            ),
            "error": None,
        })
        document["stages"]["parsed"] = "success"
    else:
        document["stages"]["parsed"] = "failed"
        document["error"] = result.get("error", "Unknown parsing error")

    save_manifest(manifest)


def record_chunking_result(manifest: dict, result: dict) -> None:
    """Writes the semantic chunking outcome of one policy into the checkpoint."""
    document = manifest["documents"][result["url"]]

    if result["status"] == "success":
        document.update({
            "chunked_path": checkpoint_artifact(
                manifest,
                "chunked",
                result["chunked_path"],
                result["url"],
            ),
            "error": None,
        })
        document["stages"]["chunked"] = "success"
    else:
        document["stages"]["chunked"] = "failed"
        document["error"] = result.get("error", "Unknown chunking error")

    save_manifest(manifest)


def record_validation_result(manifest: dict, result: dict) -> None:
    """Writes the validated payload output of one policy into the checkpoint."""
    document = manifest["documents"][result["url"]]

    if result["status"] == "success":
        document.update({
            "validated_path": checkpoint_artifact(
                manifest,
                "validated",
                result["validated_path"],
                result["url"],
            ),
            "chunk_count": result["chunk_count"],
            "chunking_methods": result["chunking_methods"],
            "error": None,
        })
        document["stages"]["validated"] = "success"
    else:
        document["stages"]["validated"] = "failed"
        document["error"] = result.get("error", "Unknown validation error")

    save_manifest(manifest)


def record_insertion_result(manifest: dict, result: dict) -> None:
    """Writes the vector-insertion outcome of one policy into the checkpoint."""
    document = manifest["documents"][result["url"]]

    if result["status"] == "success":
        document["stages"]["inserted"] = "success"
        document["error"] = None
    else:
        document["stages"]["inserted"] = "failed"
        document["error"] = result.get("error", "Unknown insertion error")

    save_manifest(manifest)


# -------------------------------------------------------------------------
# Reporting
# -------------------------------------------------------------------------

def print_ingestion_dashboard(
    manifest: dict,
    failures: list[dict],
) -> None:
    """Prints a summary of one checkpointed ingestion or resume run."""
    inserted_results = inserted_results_from_manifest(manifest)
    restricted_results = restricted_results_from_manifest(manifest)
    method_counts = Counter()
    total_chunks = 0

    for result in inserted_results:
        total_chunks += result.get("chunk_count", 0)
        method_counts.update(result.get("chunking_methods", {}))

    print("\n" + "=" * 62)
    print("LA TROBE POLICY INGESTION RUN SUMMARY")
    print("=" * 62)
    print(f"Checkpoint run ID:                 {manifest['run_id']}")
    print(f"Candidate collection:              {manifest.get('candidate_collection')}")
    print(f"Discovered/selected policy pages: {len(manifest['documents'])}")
    print(f"Changed since published ledger:   {changed_count_from_manifest(manifest)}")
    print(f"Accessible policies inserted:     {len(inserted_results)}")
    print(f"Restricted/SSO pages excluded:    {len(restricted_results)}")
    print(f"Failed or timed-out policies:     {len(failures)}")
    print(f"Validated chunks inserted:        {total_chunks}")

    print("\nChunking method counts:")
    if method_counts:
        for method, count in sorted(method_counts.items()):
            print(f"  - {method}: {count}")
    else:
        print("  None")

    if restricted_results:
        print("\nRestricted/SSO pages excluded from public-source indexing:")
        for item in restricted_results:
            print(f"  - {item['url']}")

    if failures:
        print("\nFailed or timed-out documents:")
        for item in failures:
            print(
                f"  - {item.get('title', item.get('url', 'Unknown document'))} "
                f"[{item.get('stage', 'unknown stage')}]: "
                f"{item.get('error', 'Unknown error')}"
            )

    print(
        "\nLive alias promoted:"
        + (" Yes" if manifest.get("alias_promoted") else " No")
    )
    print(
        "CDC ledger updated:"
        + (" Yes" if manifest.get("ledger_updated") else " No")
    )
    print("=" * 62 + "\n")


def stop_incomplete_run(
    manifest: dict,
    failures: list[dict],
    stage_label: str,
) -> None:
    """Records an incomplete run and explains that it can be resumed later."""
    manifest["status"] = f"failed_at_{stage_label.replace(' ', '_').lower()}"
    save_manifest(manifest)

    print(
        f"[!] {stage_label} did not complete for every accessible policy. "
        "The candidate was not promoted and the CDC ledger was not updated."
    )
    print(
        "[*] Completed stage outputs have been checkpointed. "
        "Choose 'Resume latest incomplete candidate build' after fixing the issue."
    )

    print_ingestion_dashboard(
        manifest,
        failures,
    )


# -------------------------------------------------------------------------
# Checkpointed staged candidate build and publication
# -------------------------------------------------------------------------

async def execute_manifest(
    manifest: dict,
    ledger: dict[str, str],
    is_resume: bool = False,
) -> None:
    """
    Executes pending stages in a new or resumed manifest.

    If vector insertion had already begun, a resumed run continues inserting
    into the candidate collection recorded in this manifest.
    """
    repair_missing_checkpoint_files(manifest)

    if manifest.get("alias_promoted") and not manifest.get("ledger_updated"):
        print(
            "[*] This candidate is already live but its CDC update is pending. "
            "Saving the ledger without rebuilding documents."
        )
        save_states([
            (result["url"], result["content_hash"])
            for result in inserted_results_from_manifest(manifest)
            if result.get("content_hash")
        ] + [
            (result["url"], result["content_hash"])
            for result in restricted_results_from_manifest(manifest)
            if result.get("content_hash")
        ])
        manifest["ledger_updated"] = True
        manifest["promoted"] = True
        manifest["status"] = "published"
        save_manifest(manifest)
        print_ingestion_dashboard(manifest, [])
        return

    if is_resume:
        print(f"[*] Resuming checkpointed run: {manifest['run_id']}")
        if manifest.get("candidate_collection"):
            print(
                f"[*] Reusing unpublished candidate collection: "
                f"{manifest['candidate_collection']}"
            )

    print(
        f"\n[STAGE 2: HTML STAGING] Processing pending HTML pages with at most "
        f"{MAX_WEB_STAGE_CONCURRENCY} concurrent requests..."
    )
    await stage_pending_html(
        manifest,
        ledger,
    )

    staging_failures = stage_failures(manifest, "staged")
    if staging_failures:
        stop_incomplete_run(
            manifest,
            staging_failures,
            "HTML staging",
        )
        return

    documents = accessible_documents(manifest)
    if not documents:
        manifest["status"] = "no_accessible_documents"
        save_manifest(manifest)
        print("[!] No accessible policy documents were available for processing.")
        print_ingestion_dashboard(manifest, [])
        return

    safe_workers = calculate_safe_workers()
    chunking_workers = max(1, min(safe_workers, MAX_CHUNKING_WORKERS))
    validation_workers = max(1, min(safe_workers, MAX_VALIDATION_WORKERS))
    insertion_workers = max(1, min(safe_workers, MAX_INSERTION_WORKERS))

    print(
        "[*] Controlled concurrency plan: "
        f"parsing={safe_workers}, "
        f"chunking={chunking_workers}, "
        f"validation={validation_workers}, "
        f"vector insertion={insertion_workers} worker(s)."
    )

    pending_parsing = [
        {
            "url": document["url"],
            "title": document["title"],
            "file_path": document["file_path"],
            "content_hash": document.get("content_hash"),
            "is_updated": document.get("is_updated", True),
        }
        for document in documents
        if document["stages"].get("parsed") != "success"
    ]

    if pending_parsing:
        print(
            f"\n[STAGE 3: PARSING] Parsing {len(pending_parsing)} pending "
            f"HTML file(s) with {safe_workers} worker process(es)..."
        )
        _, failures = run_stage_with_timeout(
            pending_parsing,
            parse_staged_policy,
            "parsed",
            safe_workers,
            lambda result: record_parsing_result(manifest, result),
        )

        if failures or not stage_complete_for_accessible_documents(manifest, "parsed"):
            stop_incomplete_run(
                manifest,
                failures or stage_failures(manifest, "parsed"),
                "Parsing",
            )
            return
    else:
        print("[*] Parsing checkpoint found; no documents need reparsing.")

    pending_chunking = [
        {
            "url": document["url"],
            "title": document["title"],
            "parsed_path": document["parsed_path"],
            "content_hash": document.get("content_hash"),
            "is_updated": document.get("is_updated", True),
        }
        for document in documents
        if document["stages"].get("chunked") != "success"
    ]

    if pending_chunking:
        print(
            f"\n[STAGE 4: SEMANTIC CHUNKING] Chunking {len(pending_chunking)} "
            f"pending document(s) with {chunking_workers} worker process(es)..."
        )
        _, failures = run_stage_with_timeout(
            pending_chunking,
            chunk_parsed_policy,
            "chunked",
            chunking_workers,
            lambda result: record_chunking_result(manifest, result),
        )

        if failures or not stage_complete_for_accessible_documents(manifest, "chunked"):
            stop_incomplete_run(
                manifest,
                failures or stage_failures(manifest, "chunked"),
                "Semantic chunking",
            )
            return
    else:
        print("[*] Chunking checkpoint found; no documents need rechunking.")

    pending_validation = [
        {
            "url": document["url"],
            "title": document["title"],
            "chunked_path": document["chunked_path"],
            "content_hash": document.get("content_hash"),
            "is_updated": document.get("is_updated", True),
        }
        for document in documents
        if document["stages"].get("validated") != "success"
    ]

    if pending_validation:
        print(
            f"\n[STAGE 5: PAYLOAD VALIDATION] Validating {len(pending_validation)} "
            f"pending document(s) with {validation_workers} worker process(es)..."
        )
        _, failures = run_stage_with_timeout(
            pending_validation,
            validate_chunked_policy,
            "validated",
            validation_workers,
            lambda result: record_validation_result(manifest, result),
        )

        if failures or not stage_complete_for_accessible_documents(manifest, "validated"):
            stop_incomplete_run(
                manifest,
                failures or stage_failures(manifest, "validated"),
                "Payload validation",
            )
            return
    else:
        print("[*] Validation checkpoint found; no documents need revalidation.")

    if not manifest.get("candidate_collection"):
        print("\n[STAGE 6: CANDIDATE COLLECTION] Creating a new Qdrant candidate...")
        manifest["candidate_collection"] = create_candidate_collection()
        manifest["status"] = "candidate_created"
        save_manifest(manifest)
    else:
        print(
            f"\n[STAGE 6: CANDIDATE COLLECTION] Reusing candidate: "
            f"{manifest['candidate_collection']}"
        )

    pending_insertions = [
        {
            "validated_result": {
                "url": document["url"],
                "title": document["title"],
                "validated_path": document["validated_path"],
                "content_hash": document.get("content_hash"),
                "chunk_count": document.get("chunk_count", 0),
                "chunking_methods": document.get("chunking_methods", {}),
            },
            "candidate_collection": manifest["candidate_collection"],
        }
        for document in documents
        if document["stages"].get("inserted") != "success"
    ]

    if pending_insertions:
        print(
            f"\n[STAGE 7: VECTOR INSERTION] Inserting {len(pending_insertions)} "
            f"pending policy document(s) into '{manifest['candidate_collection']}' "
            f"with {insertion_workers} worker process(es)..."
        )
        _, failures = run_stage_with_timeout(
            pending_insertions,
            insert_validated_policy,
            "inserted",
            insertion_workers,
            lambda result: record_insertion_result(manifest, result),
        )

        if failures or not stage_complete_for_accessible_documents(manifest, "inserted"):
            stop_incomplete_run(
                manifest,
                failures or stage_failures(manifest, "inserted"),
                "Vector insertion",
            )
            return
    else:
        print("[*] Insertion checkpoint found; all policy vectors are already stored.")

    print(
        "\n[STAGE 8: PROMOTION] Switching the configured alias to "
        f"candidate '{manifest['candidate_collection']}'..."
    )

    try:
        promote_candidate_collection(
            manifest["candidate_collection"]
        )
    except Exception as exc:
        manifest["status"] = "promotion_failed"
        save_manifest(manifest)

        stop_incomplete_run(
            manifest,
            [{
                "status": "failed",
                "stage": "alias promotion",
                "url": manifest["candidate_collection"],
                "title": manifest["candidate_collection"],
                "error": str(exc),
            }],
            "Alias promotion",
        )
        return

    manifest["alias_promoted"] = True
    manifest["status"] = "alias_promoted_ledger_pending"
    save_manifest(manifest)

    print("\n[STAGE 9: CDC LEDGER] Saving hashes for the published build...")

    ledger_updates = [
        (result["url"], result["content_hash"])
        for result in inserted_results_from_manifest(manifest)
        if result.get("content_hash")
    ] + [
        (result["url"], result["content_hash"])
        for result in restricted_results_from_manifest(manifest)
        if result.get("content_hash")
    ]

    save_states(ledger_updates)

    manifest["ledger_updated"] = True
    manifest["promoted"] = True
    manifest["status"] = "published"
    save_manifest(manifest)

    print_ingestion_dashboard(
        manifest,
        [],
    )


async def start_new_pipeline(
    test_limit: int | None = None,
) -> None:
    """Discovers source pages, creates a new manifest and executes the build."""
    print("\n=====================================================")
    print("   LA TROBE POLICY DB - CHECKPOINTED PARALLEL PIPELINE")
    print("=====================================================")

    print("\n[STAGE 1: DISCOVERY] Locating policy pages...")
    all_links = await scout_policy_links(WEB_HUB_URL)

    if test_limit is not None:
        selected_links = all_links[:test_limit]
        mode = f"publication_test_{test_limit}_policies"
        print(
            f"[*] Publication test mode: processing {len(selected_links)} "
            "selected policy pages through every stage."
        )
        print(
            "[!] This is a partial build. After promotion, the configured "
            "alias will represent only this selected sample."
        )
    else:
        selected_links = all_links
        mode = "full_rebuild"
        print(
            f"[*] Full rebuild mode: processing all {len(selected_links)} policies."
        )

    if not selected_links:
        print("[!] No policy links were discovered.")
        return

    manifest = create_manifest(
        selected_links,
        mode,
    )
    print(f"[*] Created checkpoint manifest: {manifest_path(manifest['run_id'])}")

    await execute_manifest(
        manifest,
        get_all_states(),
    )


async def resume_latest_pipeline() -> None:
    """Resumes the most recent candidate build that has not been fully published."""
    manifest = find_latest_incomplete_manifest()

    if manifest is None:
        print("[!] No incomplete checkpointed ingestion run was found.")
        return

    print("\n=====================================================")
    print("   RESUMING CHECKPOINTED INGESTION BUILD")
    print("=====================================================")
    print(f"[*] Manifest: {manifest_path(manifest['run_id'])}")
    print(f"[*] Current status: {manifest.get('status', 'unknown')}")

    await execute_manifest(
        manifest,
        get_all_states(),
        is_resume=True,
    )


async def run_single_policy_debug(target_url: str) -> None:
    """
    Runs one policy through staging, parsing, chunking and validation.

    No Qdrant vectors are inserted and the configured alias is not changed.
    """
    ledger = get_all_states()

    async with AsyncWebCrawler(verbose=False) as crawler:
        async with aiohttp.ClientSession() as session:
            result = await process_single_url(
                url=target_url,
                crawler=crawler,
                session=session,
                ledger=ledger,
            )

    if result.get("status") == "restricted":
        print(f"[DEBUG] Cannot process restricted policy page: {target_url}")
        return

    parsed_result = parse_staged_policy(result)
    if parsed_result["status"] != "success":
        raise RuntimeError(parsed_result["error"])

    chunked_result = chunk_parsed_policy(parsed_result)
    if chunked_result["status"] != "success":
        raise RuntimeError(chunked_result["error"])

    validated_result = validate_chunked_policy(chunked_result)
    if validated_result["status"] != "success":
        raise RuntimeError(validated_result["error"])

    print("\n" + "=" * 62)
    print("SINGLE POLICY DEBUG RESULT - NO DATABASE INSERTION")
    print("=" * 62)
    print(f"Title: {validated_result.get('title', target_url)}")
    print(f"Source: {target_url}")
    print(f"Validated output: {Path(validated_result['validated_path'])}")
    print(f"Validated chunks: {validated_result['chunk_count']}")
    print("Chunking methods:")

    for method, count in sorted(
        validated_result["chunking_methods"].items()
    ):
        print(f"  - {method}: {count}")

    print("=" * 62 + "\n")


if __name__ == "__main__":
    print("Select ingestion mode:")
    print("1. Full public HTML policy-library rebuild and alias promotion")
    print(
        f"2. {PIPELINE_TEST_DOCUMENT_LIMIT}-policy full publication test "
        "(parallel processing, alias promotion and CDC ledger update)"
    )
    print("3. Resume latest incomplete candidate build")
    print("4. Single policy debug run without database insertion")

    choice = input("Enter 1, 2, 3 or 4: ").strip()

    if choice == "1":
        asyncio.run(
            start_new_pipeline()
        )

    elif choice == "2":
        print(
            "\nWARNING: This test deliberately promotes a partial candidate "
            "collection. After promotion, the configured alias will represent "
            f"only the selected {PIPELINE_TEST_DOCUMENT_LIMIT}-policy sample."
        )

        confirmation = input(
            "Type PROMOTE TEST to run insertion, alias promotion "
            "and CDC update: "
        ).strip()

        if confirmation != "PROMOTE TEST":
            raise SystemExit("Publication-path test cancelled.")

        asyncio.run(
            start_new_pipeline(
                test_limit=PIPELINE_TEST_DOCUMENT_LIMIT,
            )
        )

    elif choice == "3":
        asyncio.run(
            resume_latest_pipeline()
        )

    elif choice == "4":
        target_url = input("Enter a public policy URL: ").strip()
        asyncio.run(
            run_single_policy_debug(target_url)
        )

    else:
        raise SystemExit("Invalid selection. Enter 1, 2, 3 or 4.")
