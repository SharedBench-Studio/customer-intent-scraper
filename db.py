"""
db.py — Pure SQLite data-access layer for the scraping-copilot dashboard.

Rules:
- No Streamlit imports anywhere in this file.
- All public functions accept an explicit db_path argument.
- All public functions return pd.DataFrame (empty on empty result,
  raise exceptions on DB errors — callers decide how to handle).
- get_db() is a context manager that guarantees connection cleanup.
"""

import sqlite3
import pandas as pd
from contextlib import contextmanager


@contextmanager
def get_db(path: str):
    """
    Context manager that opens a SQLite connection and guarantees close.

    Usage:
        with get_db(db_path) as conn:
            df = pd.read_sql_query(sql, conn)
    """
    conn = sqlite3.connect(path)
    try:
        yield conn
    finally:
        conn.close()


def query_replies(db_path: str, discussion_id: str) -> pd.DataFrame:
    """Return all replies for a single discussion, ordered by publish_date."""
    with get_db(db_path) as conn:
        return pd.read_sql_query(
            "SELECT * FROM replies WHERE parent_id = ? ORDER BY publish_date",
            conn,
            params=(discussion_id,),
        )


def query_reply_stats(db_path: str) -> pd.DataFrame:
    """Return per-discussion reply counts and concatenated reply text.

    Columns: parent_id, agg_reply_count, all_reply_text
    """
    with get_db(db_path) as conn:
        return pd.read_sql_query(
            """
            SELECT parent_id,
                   COUNT(*) as agg_reply_count,
                   GROUP_CONCAT(content, ' ') as all_reply_text
            FROM replies
            GROUP BY parent_id
            """,
            conn,
        )


def query_queries_df(db_path: str) -> pd.DataFrame:
    """Return extracted queries joined with their source discussion metadata.

    Columns: id, query_text, method, product_area, created_at,
             source_title, source_url, source_likes, source_replies
    """
    with get_db(db_path) as conn:
        return pd.read_sql_query(
            """
            SELECT q.id, q.query_text, q.method, q.product_area,
                   q.created_at, d.title as source_title, d.url as source_url,
                   d.thumbs_up_count as source_likes,
                   d.reply_count as source_replies
            FROM queries q
            LEFT JOIN discussions d ON d.id = q.source_id
            """,
            conn,
        )


def query_retrievability_df(db_path: str) -> pd.DataFrame:
    """Return retrievability results joined with query text.

    Columns: query_id, doc_path, doc_title, rank, score,
             query_text, product_area
    """
    with get_db(db_path) as conn:
        return pd.read_sql_query(
            """
            SELECT r.query_id, r.doc_path, r.doc_title, r.rank, r.score,
                   q.query_text, q.product_area
            FROM retrievability_results r
            JOIN queries q ON q.id = r.query_id
            """,
            conn,
        )
