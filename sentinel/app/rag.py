"""RAG: search past incidents via FastEmbed + pgvector."""
import logging
import os
from typing import Optional

import psycopg
from fastembed import TextEmbedding

logger = logging.getLogger(__name__)

DB_URI = os.getenv("SENTINEL_DB_URI", "postgresql://user:pass@postgres:5432/sentinel_db")
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
_embedding_model: Optional[TextEmbedding] = None


def _get_embedding_model() -> TextEmbedding:
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = TextEmbedding(model_name=EMBEDDING_MODEL)
    return _embedding_model


def _embed(text: str) -> list[float]:
    """Get embedding vector for text. FastEmbed returns numpy arrays; we convert to list for safe use."""
    model = _get_embedding_model()
    embeddings_list = list(model.embed([text]))
    if not embeddings_list:
        return []
    vec = embeddings_list[0]
    return list(vec)


def search_past_incidents(query: str, limit: int = 3) -> list[dict]:
    """Search for similar past incidents. Returns list of {error_text, fix_text}."""
    try:
        embedding = _embed(query)
        if not embedding or len(embedding) == 0:
            return []

        vector_str = "[" + ",".join(str(x) for x in embedding) + "]"

        with psycopg.connect(DB_URI) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT error_text, fix_text
                    FROM incidents
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (vector_str, limit),
                )
                rows = cur.fetchall()
                return [{"error_text": r[0], "fix_text": r[1]} for r in rows]
    except Exception as e:
        logger.warning("RAG search failed: %s", e)
        return []


def create_incidents_table(conn) -> None:
    """Create incidents table with vector column if not exists."""
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                id SERIAL PRIMARY KEY,
                error_text TEXT NOT NULL,
                fix_text TEXT NOT NULL,
                embedding vector(384)
            )
        """)
    conn.commit()


def insert_incident(conn, error_text: str, fix_text: str) -> None:
    """Insert incident with embedding."""
    embedding = _embed(error_text)
    vector_str = "[" + ",".join(str(x) for x in embedding) + "]"
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO incidents (error_text, fix_text, embedding) VALUES (%s, %s, %s::vector)",
            (error_text, fix_text, vector_str),
        )
    conn.commit()
