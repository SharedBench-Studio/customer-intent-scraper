import scrapy
from datetime import datetime, timezone


class RedditSpider(scrapy.Spider):
    name = "reddit"

    # Override settings for this spider:
    # - Bypass Playwright (settings.py routes all https through it, which Reddit's
    #   bot detection blocks). Use Scrapy's native HTTP client instead.
    # - Disable robots.txt (Reddit's robots.txt blocks crawlers, but the JSON API
    #   is their intended programmatic access path).
    custom_settings = {
        "ROBOTSTXT_OBEY": False,
        "DOWNLOAD_HANDLERS": {
            "http": "scrapy.core.downloader.handlers.http.HTTPDownloadHandler",
            "https": "scrapy.core.downloader.handlers.http11.HTTP11DownloadHandler",
        },
    }

    def __init__(self, subreddits="microsoft,microsoft365", limit=50, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.subreddits = [s.strip() for s in subreddits.split(",")]
        self.limit = int(limit)

    def start_requests(self):
        for subreddit in self.subreddits:
            url = f"https://www.reddit.com/r/{subreddit}/new.json?limit=100"
            yield scrapy.Request(
                url=url,
                callback=self.parse,
                headers={"User-Agent": "python:customer_intent_scraper:v1.0 (research/non-commercial)"},
                cb_kwargs={"subreddit": subreddit, "collected": 0},
            )

    def parse(self, response, subreddit, collected):
        try:
            data = response.json()
        except Exception as e:
            self.logger.error(f"Failed to parse JSON for r/{subreddit}: {e}")
            return

        posts = data.get("data", {}).get("children", [])
        after = data.get("data", {}).get("after")

        self.logger.info(f"r/{subreddit}: got {len(posts)} posts (collected so far: {collected})")

        for post_wrapper in posts:
            if collected >= self.limit:
                return

            post = post_wrapper.get("data", {})
            post_id = post.get("name") or post.get("id")
            title = post.get("title", "")
            author = post.get("author", "")
            score = post.get("score", 0)
            num_comments = post.get("num_comments", 0)
            permalink = post.get("permalink", "")
            selftext = post.get("selftext", "")
            created_utc = post.get("created_utc")

            # Convert Unix timestamp to ISO format
            if created_utc:
                publish_date = datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat()
            else:
                publish_date = None

            discussion_url = f"https://www.reddit.com{permalink}" if permalink else ""

            yield {
                "message_id": post_id,
                "title": title,
                "discussion_url": discussion_url,
                "author": author,
                "reply_count": num_comments,
                "thumbs_up_count": score,
                "content": selftext,
                "publish_date": publish_date,
                "replies": [],
                "platform": "Reddit",
                "sub_source": subreddit,
            }
            collected += 1

        # Paginate if we haven't hit the limit and there are more posts
        if after and collected < self.limit:
            next_url = f"https://www.reddit.com/r/{subreddit}/new.json?limit=100&after={after}"
            yield scrapy.Request(
                url=next_url,
                callback=self.parse,
                headers={"User-Agent": "python:customer_intent_scraper:v1.0 (research/non-commercial)"},
                cb_kwargs={"subreddit": subreddit, "collected": collected},
            )
