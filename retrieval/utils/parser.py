import json
import re
import hashlib
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup
from docling.document_converter import DocumentConverter
from docling.datamodel.base_models import InputFormat
from docling_core.transforms.chunker import HierarchicalChunker


# Save the structured parser output separately from the downloaded raw HTML files
PARSED_DIR = Path(__file__).resolve().parents[2] / "data" / "1_parsed"
PARSED_DIR.mkdir(parents=True, exist_ok=True)


# Load Docling only when parsing begins, rather than when the module is imported
_converter = None


def get_converter():
    """Creates and reuses one Docling converter for HTML policy documents."""
    global _converter

    if _converter is None:
        _converter = DocumentConverter()

    return _converter


# Metadata and formatting helpers
def standardize_date(date_str: str | None) -> str | None:
    """
    Converts policy dates into a consistent YYYY-MM-DD format.
    Returns None when the date is missing or cannot be parsed safely.
    """
    if not date_str or str(date_str).lower() in [
        "none",
        "null",
        "unknown",
        "not specified",
        "",
    ]:
        return None

    try:
        # Remove ordinal suffixes so values such as "8th August 2024" can be parsed
        clean_date = re.sub(
            r"(\d+)(st|nd|rd|th)",
            r"\1",
            str(date_str),
        ).strip()

        supported_formats = [
            "%d %B %Y",
            "%d %b %Y",
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%Y",
        ]

        for date_format in supported_formats:
            try:
                parsed_date = datetime.strptime(clean_date, date_format)

                # A year-only value is stored as the first day of that year
                if date_format == "%Y":
                    return parsed_date.strftime("%Y-01-01")

                return parsed_date.strftime("%Y-%m-%d")

            except ValueError:
                continue

        return None

    except Exception:
        return None


def extract_staged_source_metadata(
    html_content: str,
    file_path: str,
) -> tuple[str, str]:
    """
    Reads the original policy URL and document title saved by the crawler
    at the beginning of the staged HTML file.
    """
    header = html_content[:2048]
    comment_end = re.escape("--" + ">")

    url_pattern = rf"source_url:\s*(.*?)\s*{comment_end}"
    title_pattern = rf"document_title:\s*(.*?)\s*{comment_end}"

    url_match = re.search(url_pattern, header)
    title_match = re.search(title_pattern, header)

    if not url_match or not title_match:
        raise RuntimeError(
            f"Required source metadata headers were not found in {file_path}"
        )

    return (
        url_match.group(1).strip(),
        title_match.group(1).strip(),
    )


def _find_value_after_label(text: str, label: str) -> str | None:
    """
    Finds a metadata value shown on the line immediately after its label.
    This is used as a fallback when the HTML table structure is incomplete.
    """
    match = re.search(
        rf"{re.escape(label)}\s*\n\s*([^\n]+)",
        text,
        re.IGNORECASE,
    )

    return match.group(1).strip() if match else None


def extract_metadata_from_html(metadata_container) -> dict:
    """
    Extracts administrative metadata from the Status and Details section.
    Missing values remain None rather than being replaced with assumed values.
    """
    empty_metadata = {
        "effective_date_iso": None,
        "review_date": None,
        "responsible_manager": {
            "name": None,
            "email": None,
        },
        "enquiries_contact": {
            "name": None,
            "email": None,
            "phone": None,
        },
        "approval_body": None,
        "status": None,
    }

    if metadata_container is None:
        return empty_metadata

    values = {}
    emails = {}

    # Read key-value information from each metadata table row
    for row in metadata_container.find_all("tr"):
        cells = row.find_all(["th", "td"])

        if len(cells) < 2:
            continue

        key = cells[0].get_text(" ", strip=True).lower()
        value = cells[1].get_text(" ", strip=True)
        values[key] = value

        # Preserve contact email addresses when they are provided as mail links
        mail_link = cells[1].find(
            "a",
            href=re.compile(r"^mailto:", re.IGNORECASE),
        )

        if mail_link:
            emails[key] = mail_link["href"].split(":", 1)[1].strip()

    visible_text = metadata_container.get_text("\n", strip=True)

    # Locate fields flexibly because the policy website may vary label wording
    manager_key = next(
        (key for key in values if "responsible manager" in key),
        "responsible manager",
    )
    enquiries_key = next(
        (key for key in values if "enquiries" in key),
        "enquiries contact",
    )
    approval_key = next(
        (key for key in values if "approval" in key),
        "approval authority",
    )

    return {
        "effective_date_iso": standardize_date(
            values.get("effective date")
            or _find_value_after_label(visible_text, "Effective Date")
        ),
        "review_date": standardize_date(
            values.get("review date")
            or _find_value_after_label(visible_text, "Review Date")
        ),
        "responsible_manager": {
            "name": values.get(manager_key),
            "email": emails.get(manager_key),
        },
        "enquiries_contact": {
            "name": values.get(enquiries_key),
            "email": emails.get(enquiries_key),
            "phone": None,
        },
        "approval_body": values.get(approval_key),
        "status": values.get("status"),
    }


def _consolidate_semantic_chunks(raw_chunks) -> list[dict]:
    """
    Merges neighbouring text chunks that belong under the same heading.
    Table chunks are kept separate so that their structure is not damaged.
    """
    serialized_chunks = []

    # Convert Docling output into normal Python dictionaries before merging
    for chunk in raw_chunks:
        text = chunk.text.strip()

        if not text:
            continue

        doc_items = list(getattr(chunk.meta, "doc_items", []) or [])

        serialized_chunks.append({
            "text": text,
            "headings": list(getattr(chunk.meta, "headings", []) or []),
            "doc_items": doc_items,
            "is_table": any(
                "table" in str(getattr(item, "label", "")).lower()
                for item in doc_items
            ),
        })

    if not serialized_chunks:
        return []

    merged_chunks = []
    current_chunk = serialized_chunks[0]

    # Prevent merged text sections from becoming too large before embedding
    max_merged_characters = 2500

    for next_chunk in serialized_chunks[1:]:
        same_heading = (
            current_chunk["headings"] == next_chunk["headings"]
        )
        combined_length = (
            len(current_chunk["text"])
            + len(next_chunk["text"])
        )

        can_merge = (
            same_heading
            and not current_chunk["is_table"]
            and not next_chunk["is_table"]
            and combined_length < max_merged_characters
        )

        if can_merge:
            current_chunk["text"] = (
                f"{current_chunk['text']}\n\n{next_chunk['text']}"
            )
            current_chunk["doc_items"].extend(next_chunk["doc_items"])
        else:
            merged_chunks.append(current_chunk)
            current_chunk = next_chunk

    merged_chunks.append(current_chunk)
    return merged_chunks


# parsing workflow
def parse_and_save(file_path: str) -> str:
    """
    Parses one staged HTML policy file and saves its structured JSON output.
    Administrative metadata is extracted separately from the searchable policy text.
    """
    file_path_obj = Path(file_path)
    html_content = file_path_obj.read_text(encoding="utf-8")

    # Read the source URL and document title stored by the crawler
    source_url, document_title = extract_staged_source_metadata(
        html_content,
        file_path,
    )

    print(f"   [Docling] Processing document tree for: {document_title}")

    soup = BeautifulSoup(html_content, "html.parser")

    # Extract the injected administrative metadata before the document is chunked
    injected_metadata = soup.find("div", id="system-injected-metadata")

    if injected_metadata is not None:
        metadata = extract_metadata_from_html(injected_metadata)

        # Remove metadata from the HTML so it cannot become searchable policy content
        injected_metadata.decompose()
    else:
        metadata = extract_metadata_from_html(None)

    # Add document identity fields required for citations and later payload creation
    metadata["document_title"] = document_title
    metadata["source_url"] = source_url

    # Convert only the cleaned policy HTML into Docling's structured document format
    converter = get_converter()
    result = converter.convert_string(
        content=str(soup),
        format=InputFormat.HTML,
        name=file_path_obj.name,
    )

    # Create structure-aware chunks using headings and document layout
    chunker = HierarchicalChunker()
    raw_chunks = list(chunker.chunk(result.document))

    # Merge related text chunks without changing the original Docling objects
    merged_chunks = _consolidate_semantic_chunks(raw_chunks)

    final_chunks = []

    # Convert each parsed chunk into JSON-safe output for the next pipeline stage
    for chunk in merged_chunks:
        if not chunk["text"]:
            continue

        table_markdown = ""

        # Preserve extracted table content in Markdown for later retrieval and display
        if chunk["is_table"]:
            table_parts = []

            for item in chunk["doc_items"]:
                is_table_item = (
                    "table" in str(getattr(item, "label", "")).lower()
                )

                if is_table_item and hasattr(item, "export_to_markdown"):
                    table_parts.append(
                        item.export_to_markdown(doc=result.document)
                    )

            table_markdown = "\n\n".join(table_parts)

        final_chunks.append({
            "text": chunk["text"],
            "headings": chunk["headings"],
            "is_table": chunk["is_table"],
            "table_markdown": table_markdown,
        })

    output_data = {
        "metadata": metadata,
        "chunks": final_chunks,
    }

    # Use the source URL to produce a stable output filename for this policy
    safe_hash = hashlib.sha256(
        source_url.encode("utf-8")
    ).hexdigest()[:12]
    output_path = PARSED_DIR / f"{safe_hash}.json"

    output_path.write_text(
        json.dumps(output_data, indent=4),
        encoding="utf-8",
    )

    return str(output_path)
