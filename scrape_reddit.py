"""
Reddit scraper using the public JSON API (no credentials required).
Writes directly to discussions.db, same schema as the Scrapy pipeline.

Usage:
    python scrape_reddit.py --subreddits microsoft,microsoft365 --limit 50
"""

import argparse
import sqlite3
import time
from datetime import datetime, timezone

import requests

HEADERS = {"User-Agent": "python:customer_intent_scraper:v1.0 (research/non-commercial)"}
DB_NAME = "discussions.db"


def ensure_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS discussions (
            id TEXT PRIMARY KEY,
            source_id TEXT,
            platform TEXT,
            sub_source TEXT,
            title TEXT,
            author TEXT,
            publish_date TEXT,
            content TEXT,
            url TEXT,
            reply_count INTEGER,
            thumbs_up_count INTEGER,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS replies (
            id TEXT PRIMARY KEY,
            parent_id TEXT,
            author TEXT,
            publish_date TEXT,
            content TEXT,
            thumbs_up_count INTEGER,
            FOREIGN KEY(parent_id) REFERENCES discussions(id)
        )
    """)
    conn.commit()


def fetch_posts(subreddit, limit):
    """Yield post dicts from r/subreddit/new.json up to limit."""
    url = f"https://www.reddit.com/r/{subreddit}/new.json?limit=100"
    collected = 0

    while url and collected < limit:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except requests.HTTPError as e:
            print(f"[reddit] HTTP error for r/{subreddit}: {e}")
            break
        except requests.RequestException as e:
            print(f"[reddit] Request failed for r/{subreddit}: {e}")
            break

        data = resp.json().get("data", {})
        posts = data.get("children", [])
        after = data.get("after")

        print(f"[reddit] r/{subreddit}: fetched {len(posts)} posts (total so far: {collected})")

        for wrapper in posts:
            if collected >= limit:
                return
            post = wrapper.get("data", {})

            created_utc = post.get("created_utc")
            publish_date = (
                datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat()
                if created_utc else None
            )
            permalink = post.get("permalink", "")

            yield {
                "id": post.get("name") or post.get("id"),
                "title": post.get("title", ""),
                "url": f"https://www.reddit.com{permalink}" if permalink else "",
                "author": post.get("author", ""),
                "reply_count": post.get("num_comments", 0),
                "thumbs_up_count": post.get("score", 0),
                "content": post.get("selftext", ""),
                "publish_date": publish_date,
                "sub_source": subreddit,
            }
            collected += 1

        url = (
            f"https://www.reddit.com/r/{subreddit}/new.json?limit=100&after={after}"
            if after else None
        )

        # Be polite — Reddit allows ~60 req/min unauthenticated
        if url:
            time.sleep(1)


def save_post(conn, post):
    conn.execute("""
        INSERT OR REPLACE INTO discussions
            (id, source_id, platform, sub_source, title, author,
             publish_date, content, url, reply_count, thumbs_up_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        post["id"],
        post["id"],
        "Reddit",
        post["sub_source"],
        post["title"],
        post["author"],
        post["publish_date"],
        post["content"],
        post["url"],
        post["reply_count"],
        post["thumbs_up_count"],
    ))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--subreddits", default="microsoft,microsoft365",
                        help="Comma-separated subreddit names")
    parser.add_argument("--limit", type=int, default=50,
                        help="Max posts per subreddit")
    parser.add_argument("--db", default=DB_NAME,
                        help="SQLite database path")
    args = parser.parse_args()

    subreddits = [s.strip() for s in args.subreddits.split(",")]

    conn = sqlite3.connect(args.db)
    ensure_tables(conn)

    total = 0
    for subreddit in subreddits:
        print(f"[reddit] Scraping r/{subreddit} (limit={args.limit})")
        for post in fetch_posts(subreddit, args.limit):
            save_post(conn, post)
            total += 1
        conn.commit()
        print(f"[reddit] r/{subreddit} done.")

    conn.close()
    print(f"[reddit] Finished. Saved {total} posts total.")


if __name__ == "__main__":
    main()
