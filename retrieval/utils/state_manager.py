import sqlite3
from pathlib import Path


# Store change-detection hashes in a small local SQLite ledger.
DB_DIR = Path(__file__).resolve().parents[2] / "data"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_FILE = DB_DIR / "ingestion_ledger.db"


def init_db() -> None:
    """Creates the ingestion ledger table when it does not already exist."""
    with sqlite3.connect(str(DB_FILE)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger (
                source_path TEXT PRIMARY KEY,
                state_hash TEXT NOT NULL
            )
            """
        )
        connection.commit()


def get_all_states() -> dict[str, str]:
    """Returns source hashes from the most recently published public-source build."""
    init_db()

    with sqlite3.connect(str(DB_FILE)) as connection:
        rows = connection.execute(
            "SELECT source_path, state_hash FROM ledger"
        ).fetchall()

    return {
        source_path: state_hash
        for source_path, state_hash in rows
    }


def save_state(source_url: str, state_hash: str) -> None:
    """Stores the inspected source hash for one published policy-build record."""
    save_states([(source_url, state_hash)])


def save_states(records: list[tuple[str, str]]) -> None:
    """
    Stores source hashes from one completed public-source build in one transaction.

    This function is called only after alias promotion succeeds. Records may
    include inaccessible SSO pages that were identified and intentionally
    excluded from the publicly available indexed collection.
    """
    if not records:
        return

    init_db()

    with sqlite3.connect(str(DB_FILE)) as connection:
        connection.executemany(
            """
            INSERT OR REPLACE INTO ledger (source_path, state_hash)
            VALUES (?, ?)
            """,
            [
                (source_url, str(state_hash))
                for source_url, state_hash in records
            ],
        )
        connection.commit()
