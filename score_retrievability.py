"""
Local Markdown doc TF-IDF retrievability scorer.
Indexes a folder of .md files and scores queries from the queries table.

Usage:
    python score_retrievability.py --docs-path C:/path/to/docs --db discussions.db --top-n 5
"""

import argparse
import os
import re
import sqlite3

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def extract_title_from_markdown(text, fallback="untitled"):
    """Return the first H1 heading, or fallback if none found."""
    match = re.search(r'^#\s+(.+)$', text, re.MULTILINE)
    return match.group(1).strip() if match else fallback


def index_docs(docs_path):
    """
    Walk docs_path recursively for .md files.
    Returns list of dicts: {path, title, text}
    """
    docs = []
    for root, _, files in os.walk(docs_path):
        for fname in files:
            if not fname.endswith(".md"):
                continue
            full_path = os.path.join(root, fname)
            try:
                with open(full_path, encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            except Exception:
                continue
            fallback = os.path.splitext(fname)[0]
            docs.append({
                "path": os.path.relpath(full_path, docs_path),
                "title": extract_title_from_markdown(text, fallback=fallback),
                "text": text,
            })
    return docs


def build_index(docs):
    """
    Build TF-IDF index from a list of doc dicts.
    Returns (vectorizer, doc_matrix) — call once, reuse for all queries.
    """
    if not docs:
        return None, None
    corpus = [d["text"] for d in docs]
    vectorizer = TfidfVectorizer(stop_words="english", max_features=10000)
    try:
        doc_matrix = vectorizer.fit_transform(corpus)
    except ValueError:
        return None, None
    return vectorizer, doc_matrix


def score_query(query_text, vectorizer, doc_matrix, docs, top_n=5):
    """
    Score a single query against a pre-built TF-IDF index.
    Returns list of top_n results: {rank, doc_path, doc_title, score}
    """
    if vectorizer is None or doc_matrix is None or not docs:
        return []
    try:
        query_vec = vectorizer.transform([query_text])
    except Exception:
        return []
    scores = cosine_similarity(query_vec, doc_matrix).flatten()
    top_indices = np.argsort(scores)[::-1][:top_n]
    results = []
    for rank, idx in enumerate(top_indices, start=1):
        results.append({
            "rank": rank,
            "doc_path": docs[idx]["path"],
            "doc_title": docs[idx]["title"],
            "score": float(scores[idx]),
        })
    return results


def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS retrievability_results (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            query_id  INTEGER,
            doc_path  TEXT,
            doc_title TEXT,
            rank      INTEGER,
            score     REAL,
            tested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


def load_queries(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, query_text FROM queries")
    except sqlite3.OperationalError as e:
        conn.close()
        print(f"Error reading queries table: {e}")
        print("Tip: Run extract_queries.py first to populate the queries table.")
        return []
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def save_results(conn, results):
    conn.executemany("""
        INSERT INTO retrievability_results (query_id, doc_path, doc_title, rank, score)
        VALUES (:query_id, :doc_path, :doc_title, :rank, :score)
    """, results)
    # Do not commit here — caller commits once after all results are saved


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs-path", required=True, help="Path to folder of .md files")
    parser.add_argument("--db", default="discussions.db")
    parser.add_argument("--top-n", type=int, default=5)
    args = parser.parse_args()

    print(f"Indexing docs from {args.docs_path}...")
    docs = index_docs(args.docs_path)
    if not docs:
        print("No .md files found. Check --docs-path.")
        return
    print(f"  {len(docs)} documents indexed.")

    print(f"Loading queries from {args.db}...")
    queries = load_queries(args.db)
    if not queries:
        print("No queries found. Run extract_queries.py first.")
        return
    print(f"  {len(queries)} queries loaded.")

    # Build index once before the query loop
    vectorizer, doc_matrix = build_index(docs)
    if vectorizer is None:
        print("Failed to build document index.")
        return

    conn = sqlite3.connect(args.db)
    ensure_table(conn)
    try:
        conn.execute("DELETE FROM retrievability_results")
        total = 0
        for i, q in enumerate(queries):
            results = score_query(q["query_text"], vectorizer, doc_matrix, docs, top_n=args.top_n)
            rows = [{**r, "query_id": q["id"]} for r in results]
            save_results(conn, rows)
            total += len(rows)
            if (i + 1) % 100 == 0:
                print(f"  Scored {i + 1}/{len(queries)} queries...")
        conn.commit()  # Single commit — covers DELETE + all inserts atomically
    except sqlite3.Error as e:
        print(f"Error saving results to database: {e}")
        return
    finally:
        conn.close()

    print(f"Done. {total} results saved to 'retrievability_results' table.")


if __name__ == "__main__":
    main()
