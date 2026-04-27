import sqlite3
import os

DB_FILE = "ingestion_ledger.db"

def init_db():
    """Initializes the SQLite database and table if it doesn't exist."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ledger (
                source_path TEXT PRIMARY KEY,
                state_hash TEXT
            )
        ''')
        conn.commit()

def get_all_states():
    """Returns the full ledger as a dictionary for fast batch Change Data Capture."""
    init_db()
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT source_path, state_hash FROM ledger')
        return {row[0]: row[1] for row in cursor.fetchall()}

def save_state(source_path: str, state_hash: str):
    """Upserts a single record to the SQLite database instantly. ACIDs compliant."""
    init_db()
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO ledger (source_path, state_hash)
            VALUES (?, ?)
        ''', (source_path, str(state_hash)))
        conn.commit()