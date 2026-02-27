"""
Rule-based query extraction from scraped discussions.
Extracts real customer questions to use as AI retrievability test queries.

Usage:
    python extract_queries.py --db discussions.db

Future (LLM upgrade): see docs/plans/query-extraction-llm-upgrade.md
"""

import argparse
import re
import sqlite3


MIN_TITLE_LENGTH = 10       # skip titles shorter than this
MAX_QUERY_LENGTH = 200      # skip titles longer than this (likely noise)
MAX_CONTENT_QUESTIONS = 3   # max questions extracted per discussion content

# Words/phrases that commonly precede a question but are not part of it
_PREAMBLE_RE = re.compile(
    r'^(?:(?:also|and|but|or|so|plus|additionally|furthermore|likewise|besides)'
    r'(?:\s*,\s*|\s+))+',
    re.IGNORECASE,
)


def _strip_preamble(text):
    """Remove leading conjunctions/transitions that precede the actual question."""
    return _PREAMBLE_RE.sub("", text).strip()


def extract_queries_from_discussion(discussion):
    """
    Extract query candidates from a single discussion dict.
    Returns list of dicts: {query_text, source_id, method, product_area}
    """
    queries = []
    seen_texts = set()
    title = (discussion.get("title") or "").strip()
    content = (discussion.get("content") or "").strip()
    source_id = discussion.get("id")
    product_area = discussion.get("analysis_product_area")

    def add(text, method):
        text = text.strip()
        if text and text not in seen_texts:
            seen_texts.add(text)
            queries.append({
                "query_text": text,
                "source_id": source_id,
                "method": method,
                "product_area": product_area,
            })

    # Rule 1: Title is a question
    if title.endswith("?") and MIN_TITLE_LENGTH <= len(title) <= MAX_QUERY_LENGTH:
        add(title, "title_question")

    # Rule 2: Sentences in content that end with ?
    if content:
        sentences = re.split(r'(?<=[.!?])\s+', content)
        count = 0
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence.endswith("?") and MIN_TITLE_LENGTH <= len(sentence) <= MAX_QUERY_LENGTH:
                # Strip leading preamble (e.g. "Also, " / "And, ") before a question word
                sentence = _strip_preamble(sentence)
                if sentence and MIN_TITLE_LENGTH <= len(sentence) <= MAX_QUERY_LENGTH:
                    add(sentence, "content_question")
                    count += 1
                    if count >= MAX_CONTENT_QUESTIONS:
                        break

    # Rule 3: Short non-question title treated as implicit query
    if (not title.endswith("?")
            and MIN_TITLE_LENGTH <= len(title) <= MAX_QUERY_LENGTH
            and not queries):  # only if no questions found yet
        add(title, "title_implicit")

    return queries


def deduplicate_queries(queries):
    """Remove exact duplicate query_text values, keeping first occurrence."""
    seen = set()
    result = []
    for q in queries:
        if q["query_text"] not in seen:
            seen.add(q["query_text"])
            result.append(q)
    return result


def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS queries (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            query_text   TEXT NOT NULL,
            source_id    TEXT,
            method       TEXT,
            product_area TEXT,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


def load_discussions(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, title, content, analysis_product_area FROM discussions")
    except sqlite3.OperationalError as e:
        conn.close()
        print(f"Error reading discussions table: {e}")
        print("Tip: Make sure discussions.db exists and has been populated by the scraper.")
        return []
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def save_queries(conn, queries):
    conn.executemany("""
        INSERT INTO queries (query_text, source_id, method, product_area)
        VALUES (:query_text, :source_id, :method, :product_area)
    """, queries)
    conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="discussions.db")
    args = parser.parse_args()

    print(f"Loading discussions from {args.db}...")
    discussions = load_discussions(args.db)
    print(f"  {len(discussions)} discussions loaded.")

    all_queries = []
    for d in discussions:
        all_queries.extend(extract_queries_from_discussion(d))

    all_queries = deduplicate_queries(all_queries)
    print(f"  {len(all_queries)} unique queries extracted.")

    conn = sqlite3.connect(args.db)
    ensure_table(conn)
    try:
        # DELETE and save_queries are intentionally in the same transaction:
        # conn.commit() is only called inside save_queries, so if save_queries
        # fails, the DELETE is also rolled back and the table stays intact.
        conn.execute("DELETE FROM queries")
        save_queries(conn, all_queries)
    except sqlite3.Error as e:
        conn.close()
        print(f"Error saving queries to database: {e}")
        return
    conn.close()
    print("Done. Queries saved to 'queries' table.")


if __name__ == "__main__":
    main()
