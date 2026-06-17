import json
import sqlite3
from datetime import datetime, timezone
import sqlite_vec
from typing import List

from app.constants import MEMORY_DB, MEMORY_DIR

def get_db_connection() -> sqlite3.Connection:
    """
    Creates and returns a connection to MEMORY_DB with sqlite_vec loaded.
    """
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(MEMORY_DB))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    """
    Initialises tables and FTS5 triggers inside the memory database.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Metadata chunks table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            rowid INTEGER PRIMARY KEY AUTOINCREMENT,
            conv_id TEXT,
            text TEXT,
            created_at TEXT
        )
    """)
    
    # 2. sqlite-vec virtual table for 768-dimensional float32 embeddings
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
            rowid INTEGER PRIMARY KEY,
            embedding float[768]
        )
    """)
    
    # 3. FTS5 search virtual table
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            text,
            content='chunks',
            content_rowid='rowid'
        )
    """)
    
    # 4. Triggers to auto-synchronise standard table insertions and deletions with FTS5
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
          INSERT INTO chunks_fts(rowid, text) VALUES (new.rowid, new.text);
        END;
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
          INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES('delete', old.rowid, old.text);
        END;
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
          INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES('delete', old.rowid, old.text);
          INSERT INTO chunks_fts(rowid, text) VALUES (new.rowid, new.text);
        END;
    """)
    
    conn.commit()
    conn.close()

def add_chunk(conv_id: str, text: str, embedding: List[float]) -> int:
    """
    Inserts a metadata record and its vector embedding, returning the new rowid.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Insert metadata
        cursor.execute(
            "INSERT INTO chunks (conv_id, text, created_at) VALUES (?, ?, ?)",
            (conv_id, text, timestamp)
        )
        rowid = cursor.lastrowid
        
        # Insert vector embedding as JSON array
        embedding_json = json.dumps(embedding)
        cursor.execute(
            "INSERT INTO vec_chunks (rowid, embedding) VALUES (?, ?)",
            (rowid, embedding_json)
        )
        conn.commit()
        return rowid
    finally:
        conn.close()
