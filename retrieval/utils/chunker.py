import json
import re
import time
import numpy as np
import requests
from pathlib import Path

from retrieval.config import (
    DENSE_MODEL_NAME,
    DENSE_VECTOR_SIZE,
    OLLAMA_EMBED_URL,
)


# Load spaCy sentence splitting when available.
# The basic regex fallback allows the pipeline to continue if spaCy is not installed.
try:
    import spacy
    nlp = spacy.load("en_core_web_sm")
except (ImportError, OSError):
    print(
        "[WARNING] spaCy or model 'en_core_web_sm' is unavailable. "
        "Using basic sentence splitting instead."
    )
    nlp = None


# Store the final retrieval-ready chunks separately from the parsed document output.
CHUNKED_DIR = Path(__file__).resolve().parents[2] / "data" / "2_chunked"
CHUNKED_DIR.mkdir(parents=True, exist_ok=True)


# Semantic chunking settings
BUFFER_SIZE = 1              # Number of neighbouring sentences included when comparing meaning
BATCH_SIZE = 16              # Number of sentence groups embedded in one Ollama request
BREAKPOINT_PERCENTILE = 90   # Higher distances are treated as likely topic boundaries
VARIANCE_FLOOR = 0.05        # Avoid unnecessary semantic splitting when distances are very similar
MIN_CHUNK_SIZE = 400         # Preferred minimum text length before producing a chunk
MAX_CHUNK_SIZE = 1500        # Maximum stored chunk length, including its breadcrumb


# Ollama embedding helper
def safe_get_embeddings(
    texts: list[str],
    retries: int = 3,
) -> list[list[float]]:
    """
    Generates dense embeddings for text batches using Ollama.

    Each response is checked before it is accepted so that incomplete or
    incorrectly sized embeddings do not affect semantic boundary detection.
    """
    vectors: list[list[float]] = []

    # Process several sentence groups in one request to reduce repeated API calls.
    for start_index in range(0, len(texts), BATCH_SIZE):
        batch = texts[start_index:start_index + BATCH_SIZE]
        payload = {
            "model": DENSE_MODEL_NAME,
            "input": batch,
        }

        last_error: Exception | None = None
        validated_vectors: list[list[float]] | None = None

        # Retry temporary Ollama failures before stopping the chunking stage.
        for attempt in range(retries):
            try:
                response = requests.post(
                    OLLAMA_EMBED_URL,
                    json=payload,
                    timeout=30,
                )
                response.raise_for_status()
                data = response.json()

                returned_vectors = data.get("embeddings")

                if not returned_vectors:
                    raise ValueError(
                        "Ollama returned an empty or malformed embedding array."
                    )

                # There must be exactly one embedding for every input sentence group.
                if len(returned_vectors) != len(batch):
                    raise ValueError(
                        f"Embedding count mismatch. Expected {len(batch)}, "
                        f"received {len(returned_vectors)}."
                    )

                # Qdrant expects all dense vectors to use the configured dimension.
                for vector in returned_vectors:
                    if len(vector) != DENSE_VECTOR_SIZE:
                        raise ValueError(
                            f"Vector dimension mismatch. "
                            f"Expected {DENSE_VECTOR_SIZE}, "
                            f"received {len(vector)}."
                        )

                validated_vectors = returned_vectors
                break

            except Exception as exc:
                last_error = exc

                if attempt < retries - 1:
                    time.sleep(2 ** attempt)

        if validated_vectors is None:
            raise RuntimeError(
                f"Embedding failed for batch starting at index "
                f"{start_index}: {last_error}"
            ) from last_error

        vectors.extend(validated_vectors)

    return vectors


# Text and table splitting helpers
def _safe_breadcrumb(breadcrumb: str) -> str:
    """
    Shortens very long heading paths so that enough space remains
    for the actual policy content inside each stored chunk.
    """
    max_breadcrumb_length = 300

    if len(breadcrumb) <= max_breadcrumb_length:
        return breadcrumb

    return breadcrumb[:max_breadcrumb_length - 3] + "..."


def _content_budget(breadcrumb: str) -> int:
    """
    Calculates how many characters remain for policy text after the
    breadcrumb prefix has been added to the stored chunk.
    """
    prefix_length = len(f"[{breadcrumb}]\n")
    return max(1, MAX_CHUNK_SIZE - prefix_length)


def _find_safe_split_position(text_window: str, max_length: int) -> int:
    """
    Finds a suitable place to split a long section without cutting through words.

    Paragraph and sentence boundaries are preferred. If no strong boundary is
    available near the limit, the function splits at the last available space.
    """
    minimum_length = int(max_length * 0.60)

    # Try stronger content boundaries first so policy clauses remain readable.
    boundary_patterns = [
        r"\n\n",                    # End of a paragraph
        r"(?<=[.!?])\s+",           # End of a sentence
        r"(?<=;)\s+",               # End of a long clause
        r"(?<=:)\s+",               # End of an introductory clause
        r"\s+",                     # Final fallback: end of a word
    ]

    for pattern in boundary_patterns:
        matches = [
            match.start()
            for match in re.finditer(pattern, text_window)
            if minimum_length <= match.start() <= max_length
        ]

        if matches:
            return matches[-1]

    # This should only occur for unusually long unbroken strings.
    return max_length
def _move_detached_marker_to_next_chunk(
    text: str,
    split_position: int,
) -> int:
    """
    Moves a numbered marker into the next chunk when a split would
    otherwise separate it from the rule that follows.
    """
    left_text = text[:split_position].rstrip()

    detached_marker = re.search(
        r"(?:\(\d+\)|\d+\.)\s*$",
        left_text,
    )

    if detached_marker:
        return detached_marker.start()

    return split_position


def _split_text_without_loss(
    text: str,
    breadcrumb: str,
    method: str,
) -> list[dict]:
    """
    Splits oversized text into retrieval-sized chunks without cutting words
    or separating a numbered marker from its related rule.
    """
    available_length = _content_budget(breadcrumb)
    remaining_text = text.strip()
    chunks = []

    while len(remaining_text) > available_length:
        text_window = remaining_text[:available_length + 1]

        split_position = _find_safe_split_position(
            text_window,
            available_length,
        )

        # Keep list numbers and policy clause markers with their following text.
        split_position = _move_detached_marker_to_next_chunk(
            remaining_text,
            split_position,
        )

        slice_text = remaining_text[:split_position].rstrip()

        chunks.append({
            "content": f"[{breadcrumb}]\n{slice_text}",
            "chunking_method": method,
        })

        remaining_text = remaining_text[split_position:].lstrip()

    if remaining_text:
        chunks.append({
            "content": f"[{breadcrumb}]\n{remaining_text}",
            "chunking_method": method,
        })

    return chunks
def _split_markdown_table(
    table_text: str,
    breadcrumb: str,
) -> list[dict]:
    """
    Splits Markdown tables into smaller chunks while repeating the header row.

    Repeating the header keeps each table section understandable when it is
    retrieved separately from the rest of the original table.
    """
    lines = table_text.strip().split("\n")

    # Preserve all text through character splitting when table structure is unclear.
    if (
        len(lines) < 3
        or "|" not in lines[0]
        or "|-" not in lines[1].replace(" ", "")
    ):
        return _split_text_without_loss(
            table_text,
            breadcrumb,
            "Table-Character-Split-Fallback",
        )

    header_row = lines[0]
    separator_row = lines[1]
    base_overhead = len(header_row) + len(separator_row) + 2
    available_length = _content_budget(breadcrumb)
    data_row_budget = available_length - base_overhead

    # A single row may be too large to preserve as a valid small table chunk.
    # In this case, keep all text using a character-based fallback split.
    if data_row_budget <= 0 or any(
        len(row) + 1 > data_row_budget
        for row in lines[2:]
    ):
        return _split_text_without_loss(
            table_text,
            breadcrumb,
            "Table-Long-Row-Character-Split",
        )

    sub_tables = []
    current_table_lines = [header_row, separator_row]
    current_length = base_overhead

    # Add table rows until the next row would exceed the available chunk size.
    for row in lines[2:]:
        row_length = len(row) + 1

        if (
            current_length + row_length > available_length
            and len(current_table_lines) > 2
        ):
            sub_tables.append("\n".join(current_table_lines))

            # Start the next table section with the original header.
            current_table_lines = [header_row, separator_row, row]
            current_length = base_overhead + row_length
        else:
            current_table_lines.append(row)
            current_length += row_length

    if len(current_table_lines) > 2:
        sub_tables.append("\n".join(current_table_lines))

    return [
        {
            "content": f"[{breadcrumb}]\n{sub_table}",
            "chunking_method": "Lossless-Table-Split",
        }
        for sub_table in sub_tables
    ]

def _repair_detached_number_markers(sentences: list[str]) -> list[str]:
    """
    Joins standalone numbered markers to the sentence that follows them.

    This prevents list items such as '2.' and policy clauses such as '(78)'
    from being stored separately from the rule they introduce.
    """
    repaired_sentences = []
    index = 0

    while index < len(sentences):
        current_sentence = sentences[index].strip()

        # Match standalone list numbers such as '2.' and clause numbers such as '(78)'.
        is_detached_marker = bool(
            re.fullmatch(r"(?:\d+\.|\(\d+\))", current_sentence)
        )

        if is_detached_marker and index + 1 < len(sentences):
            combined_sentence = (
                f"{current_sentence} {sentences[index + 1].strip()}"
            )
            repaired_sentences.append(combined_sentence)
            index += 2
        else:
            repaired_sentences.append(current_sentence)
            index += 1

    return repaired_sentences
def _custom_semantic_split(
    text: str,
    breadcrumb: str,
) -> list[dict]:
    """
    Splits long policy text using sentence boundaries and semantic changes.

    Short blocks are kept as they are. Longer blocks are divided at points
    where neighbouring sentence groups become meaningfully different.
    """
    budget = _content_budget(breadcrumb)
    effective_min_chunk_size = min(MIN_CHUNK_SIZE, budget)

    # Keep content unchanged when it already fits within one retrieval chunk.
    if len(text.strip()) <= budget:
        return [{
            "content": f"[{breadcrumb}]\n{text}",
            "chunking_method": "Atomic-Pass",
        }]

    # Split the original text into sentences without rewriting policy wording.
    if nlp:
        doc = nlp(text)
        sentences = [
            sentence.text.strip()
            for sentence in doc.sents
            if sentence.text.strip()
        ]
    else:
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", text)
            if sentence.strip()
        ]
    # Keep numbered list markers attached to the rule they introduce.
    sentences = _repair_detached_number_markers(sentences)

    # If sentence boundaries cannot be identified, preserve content by length.
    if len(sentences) <= 1:
        return _split_text_without_loss(
            text,
            breadcrumb,
            "Character-Split-Fallback",
        )

    # Build small sentence windows so each embedding has nearby context.
    sentence_buffers = []

    for index in range(len(sentences)):
        start = max(0, index - BUFFER_SIZE)
        end = min(len(sentences), index + BUFFER_SIZE + 1)
        sentence_buffers.append(" ".join(sentences[start:end]))

    vectors = safe_get_embeddings(sentence_buffers)

    # Measure semantic change between neighbouring sentence windows.
    distances = []

    for index in range(len(vectors) - 1):
        first_vector = np.array(vectors[index])
        second_vector = np.array(vectors[index + 1])

        first_norm = np.linalg.norm(first_vector)
        second_norm = np.linalg.norm(second_vector)

        if first_norm == 0 or second_norm == 0:
            distances.append(0.0)
            continue

        similarity = np.clip(
            np.dot(first_vector, second_vector)
            / (first_norm * second_norm),
            -1.0,
            1.0,
        )
        distances.append(1.0 - similarity)

    # Skip semantic breakpoints where the whole section is already very similar.
    if not distances or np.std(distances) < VARIANCE_FLOOR:
        method_flag = "Semantic-Variance-Bypass"
        breakpoints = []
    else:
        method_flag = "Hierarchical-Semantic-Optimized"
        threshold = np.percentile(
            distances,
            BREAKPOINT_PERCENTILE,
        )
        breakpoints = [
            index
            for index, distance in enumerate(distances)
            if distance > threshold
        ]

    raw_semantic_chunks = []
    start_index = 0

    # Split at detected boundaries without repeating sentences across chunks.
    for breakpoint in breakpoints:
        end_index = breakpoint + 1
        raw_semantic_chunks.append(
            " ".join(sentences[start_index:end_index])
        )
        start_index = end_index

    if start_index < len(sentences):
        raw_semantic_chunks.append(
            " ".join(sentences[start_index:])
        )

    final_payloads = []
    working_buffer = ""

    # Merge very small semantic sections while still respecting the size limit.
    for chunk in raw_semantic_chunks:
        candidate_text = (
            f"{working_buffer} {chunk}".strip()
            if working_buffer
            else chunk
        )

        if len(candidate_text) < effective_min_chunk_size:
            working_buffer = candidate_text

        elif len(candidate_text) > budget:
            if working_buffer:
                final_payloads.append({
                    "content": f"[{breadcrumb}]\n{working_buffer}",
                    "chunking_method": method_flag,
                })

            # Preserve oversized semantic sections using a non-lossy fallback split.
            if len(chunk) > budget:
                lossless_splits = _split_text_without_loss(
                    chunk,
                    breadcrumb,
                    "Hard-Cut-Limit",
                )

                final_payloads.extend(lossless_splits[:-1])

                # Carry the final smaller part forward in case it can be merged.
                working_buffer = lossless_splits[-1]["content"].removeprefix(
                    f"[{breadcrumb}]\n"
                )
            else:
                working_buffer = chunk

        else:
            final_payloads.append({
                "content": f"[{breadcrumb}]\n{candidate_text}",
                "chunking_method": method_flag,
            })
            working_buffer = ""

    if working_buffer:
        final_payloads.append({
            "content": f"[{breadcrumb}]\n{working_buffer}",
            "chunking_method": method_flag,
        })

    return final_payloads

# Stage 2 chunking workflow
def apply_semantic_chunking(file_path: str) -> str:
    """
    Reads one parsed policy JSON file, prepares retrieval-sized chunks,
    and saves the Stage 2 output for later embedding and database insertion.
    """
    with open(file_path, "r", encoding="utf-8") as file:
        data = json.load(file)

    metadata = data["metadata"]
    raw_chunks = data["chunks"]
    document_title = metadata["document_title"]

    print(
        f"   [Chunking] Processing {len(raw_chunks)} "
        f"structural blocks for {document_title}..."
    )

    processed_chunks = []

    for chunk in raw_chunks:
        raw_breadcrumb = (
            f"{document_title} > " + " > ".join(chunk["headings"])
            if chunk["headings"]
            else document_title
        )

        # Keep the breadcrumb useful for citations without allowing it to use
        # most of the available chunk length.
        breadcrumb = _safe_breadcrumb(raw_breadcrumb)

        is_table = chunk["is_table"]
        text = (
            chunk["table_markdown"]
            if is_table
            else chunk["text"]
        )

        if not text.strip():
            continue

        # Table chunks use row-aware splitting; text chunks use semantic splitting.
        if is_table:
            sub_chunks = _split_markdown_table(text, breadcrumb)

            for sub_chunk in sub_chunks:
                sub_chunk["is_table"] = True
                sub_chunk["breadcrumb"] = breadcrumb
                sub_chunk["chunk_index"] = len(processed_chunks)
                processed_chunks.append(sub_chunk)
        else:
            sub_chunks = _custom_semantic_split(text, breadcrumb)

            for sub_chunk in sub_chunks:
                sub_chunk["is_table"] = False
                sub_chunk["breadcrumb"] = breadcrumb
                sub_chunk["chunk_index"] = len(processed_chunks)
                processed_chunks.append(sub_chunk)

    output_data = {
        "metadata": metadata,
        "chunks": processed_chunks,
    }

    output_path = CHUNKED_DIR / Path(file_path).name

    output_path.write_text(
        json.dumps(output_data, indent=4),
        encoding="utf-8",
    )

    return str(output_path)