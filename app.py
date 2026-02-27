import streamlit as st
import pandas as pd
import sqlite3
import os
import plotly.express as px
import subprocess
import sys
from collections import Counter
import re
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="Copilot Feedback Analysis", layout="wide")

# Ensure Playwright browsers are installed
try:
    if not os.path.exists("playwright_installed.flag"):
        with st.spinner("Installing Playwright browsers... This runs only once per reboot."):
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
            # Create a flag file to avoid re-installing
            with open("playwright_installed.flag", "w") as f:
                f.write("installed")
except Exception as e:
    st.error(f"Failed to install Playwright: {e}")

st.title("Microsoft 365 Copilot Feedback Analysis")

# --- Sidebar: Scraper Management ---
st.sidebar.header("Scraper Management")
with st.sidebar.expander("Run Scraper"):
    scraper_type = st.selectbox("Select Scraper", ["Tech Community", "Reddit"])
    
    if scraper_type == "Tech Community":
        default_urls = "https://techcommunity.microsoft.com/category/microsoft365copilot/discussions/microsoft365copilot, https://techcommunity.microsoft.com/category/microsoft365/discussions/admincenter"
        urls_input = st.text_area("URLs to Scrape (comma separated)", value=default_urls, height=100)
        max_pages = st.number_input("Max Pages per Board (0 for unlimited)", min_value=0, value=10, step=1, help="Limit the number of pages to scrape per board.")
    else:
        default_subreddits = "microsoft,microsoft365,Office365,sharepoint,teams"
        subreddits_input = st.text_area("Subreddits (comma separated)", value=default_subreddits, height=100)
        limit_posts = st.number_input("Limit Posts per Subreddit", min_value=10, value=50, step=10)

    if st.button("Run Scraper Now"):
        st.info("Scraper started. Streaming logs below...")
        log_placeholder = st.empty()
        full_logs = []
        
        try:
            # Construct command
            if scraper_type == "Tech Community":
                cmd = [
                    sys.executable, "-m", "scrapy", "crawl", "techcommunity", 
                    "-a", f"urls={urls_input}"
                ]
                if max_pages > 0:
                    cmd.extend(["-a", f"max_pages={max_pages}"])
            else:
                cmd = [
                    sys.executable, "scrape_reddit.py",
                    "--subreddits", subreddits_input,
                    "--limit", str(limit_posts)
                ]
            
            # Run process with Popen for real-time output
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, # Merge stderr into stdout
                text=True,
                bufsize=1, # Line buffered
                encoding='utf-8',
                errors='replace'
            )
            
            # Read output line by line
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    full_logs.append(line)
                    # Update logs every few lines or just show the last 20 lines to avoid UI lag
                    # We join the last 20 lines for the preview, but keep full logs
                    log_preview = "".join(full_logs[-20:])
                    log_placeholder.code(log_preview, language="text")
            
            rc = process.poll()
            
            if rc == 0:
                st.success("Scraper finished successfully!")
                # Clear cache to ensure new data is loaded
                st.cache_data.clear()
                st.rerun()
            else:
                st.error(f"Scraper failed with return code {rc}.")
            
            # Show full logs in an expander at the end
            with st.expander("View Full Scraper Logs"):
                st.code("".join(full_logs))
                
        except Exception as e:
            st.error(f"An error occurred: {e}")

with st.sidebar.expander("Run Analysis"):
    analysis_type = st.radio("Analysis Type", ["Local (Keyword)", "AI (Azure OpenAI)"])
    
    if analysis_type == "Local (Keyword)":
        st.write("Fast, free, runs offline using keyword matching.")
        if st.button("Run Local Analysis"):
            st.info("Analysis started...")
            try:
                result = subprocess.run(
                    [sys.executable, "analyze_local.py"],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    st.success("Analysis finished successfully!")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error("Analysis failed.")
                    st.code(result.stderr)
            except Exception as e:
                st.error(f"An error occurred: {e}")
    else:
        st.write("Slower, costs Azure credits, but higher accuracy using GPT-4o.")
        limit_ai = st.number_input("Limit items to analyze (0 for all)", min_value=0, value=10, step=10)
        
        if st.button("Run AI Analysis"):
            # Check env vars first
            if not os.getenv("AZURE_OPENAI_API_KEY"):
                st.error("Missing AZURE_OPENAI_API_KEY in .env file.")
            else:
                st.info("AI Analysis started. This may take a while...")
                log_placeholder = st.empty()
                
                try:
                    cmd = [
                        sys.executable, "analyze_intent.py",
                        "--limit", str(limit_ai)
                    ]
                    
                    process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                        encoding='utf-8',
                        errors='replace'
                    )
                    
                    full_logs = []
                    while True:
                        line = process.stdout.readline()
                        if not line and process.poll() is not None:
                            break
                        if line:
                            full_logs.append(line)
                            log_placeholder.code("".join(full_logs[-10:]), language="text")
                            
                    if process.poll() == 0:
                        st.success("AI Analysis finished successfully!")
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error("AI Analysis failed.")
                        st.code("".join(full_logs))
                        
                except Exception as e:
                    st.error(f"An error occurred: {e}")

with st.sidebar.expander("Query Bank"):
    st.write("Extract customer queries and test doc retrievability.")

    if st.button("Extract Queries"):
        st.info("Extracting queries from discussions...")
        result = subprocess.run(
            [sys.executable, "extract_queries.py", "--db", "discussions.db"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            st.success("Queries extracted!")
            st.code(result.stdout)
            st.cache_data.clear()
        else:
            st.error("Extraction failed.")
            st.code(result.stderr)

    st.markdown("---")
    docs_path = st.text_input("Docs folder path", placeholder="C:/path/to/your/docs")
    top_n = st.number_input("Top N results per query", min_value=1, max_value=10, value=5)

    if st.button("Run Retrievability Test"):
        if not docs_path:
            st.warning("Enter a docs folder path first.")
        else:
            st.info("Scoring queries against docs...")
            result = subprocess.run(
                [sys.executable, "test_retrievability.py",
                 "--docs-path", docs_path,
                 "--db", "discussions.db",
                 "--top-n", str(top_n)],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                st.success("Retrievability test complete!")
                st.code(result.stdout)
                st.cache_data.clear()
            else:
                st.error("Test failed.")
                st.code(result.stderr)

if st.sidebar.button("Refresh Data"):
    st.cache_data.clear()
    st.rerun()

# Load data
@st.cache_data
def load_data(ttl_hash=None):
    # ttl_hash is a dummy argument to force cache invalidation when the file changes
    del ttl_hash 
    db_path = "discussions.db"
    if not os.path.exists(db_path):
        return pd.DataFrame()
        
    try:
        conn = sqlite3.connect(db_path)
        query = "SELECT * FROM discussions"
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        # Convert date
        if "publish_date" in df.columns:
            df["publish_date"] = pd.to_datetime(df["publish_date"], errors='coerce', utc=True)
            
        # Rename analysis columns to match expected format
        column_mapping = {
            "analysis_category": "category",
            "analysis_product_area": "product_area",
            "analysis_sentiment": "sentiment",
            "analysis_intent": "intent",
            "analysis_author_role": "author_role",
            "analysis_cluster_id": "cluster_id"
        }
        df = df.rename(columns=column_mapping)
        
        # Normalize sub_source to lowercase to merge duplicates
        if "sub_source" in df.columns:
            df["sub_source"] = df["sub_source"].str.lower()

        return df
    except Exception as e:
        st.error(f"Error loading database: {e}")
        return pd.DataFrame()

def _query_replies(db_path, discussion_id):
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        "SELECT * FROM replies WHERE parent_id = ? ORDER BY publish_date",
        conn, params=(discussion_id,)
    )
    conn.close()
    return df


def load_replies(discussion_id):
    db_path = "discussions.db"
    if not os.path.exists(db_path):
        return pd.DataFrame()
    try:
        return _query_replies(db_path, discussion_id)
    except Exception as e:
        st.error(f"Error loading replies: {e}")
        return pd.DataFrame()


@st.cache_data
def load_reply_stats(ttl_hash=None):
    """Load per-discussion reply counts and aggregated reply text for Topic Explorer."""
    del ttl_hash
    db_path = "discussions.db"
    if not os.path.exists(db_path):
        return pd.DataFrame()
    try:
        conn = sqlite3.connect(db_path)
        df = pd.read_sql_query("""
            SELECT parent_id,
                   COUNT(*) as agg_reply_count,
                   GROUP_CONCAT(content, ' ') as all_reply_text
            FROM replies
            GROUP BY parent_id
        """, conn)
        conn.close()
        return df
    except Exception as e:
        st.error(f"Error loading reply stats: {e}")
        return pd.DataFrame()


@st.cache_data
def load_queries_df(ttl_hash=None):
    """Load extracted queries with their source discussion title."""
    del ttl_hash
    db_path = "discussions.db"
    if not os.path.exists(db_path):
        return pd.DataFrame()
    try:
        conn = sqlite3.connect(db_path)
        df = pd.read_sql_query("""
            SELECT q.id, q.query_text, q.method, q.product_area,
                   q.created_at, d.title as source_title, d.url as source_url
            FROM queries q
            LEFT JOIN discussions d ON d.id = q.source_id
        """, conn)
        conn.close()
        return df
    except Exception as e:
        st.error(f"Error loading queries: {e}")
        return pd.DataFrame()


@st.cache_data
def load_retrievability_df(ttl_hash=None):
    """Load retrievability results joined with query text."""
    del ttl_hash
    db_path = "discussions.db"
    if not os.path.exists(db_path):
        return pd.DataFrame()
    try:
        conn = sqlite3.connect(db_path)
        df = pd.read_sql_query("""
            SELECT r.query_id, r.doc_path, r.doc_title, r.rank, r.score,
                   q.query_text, q.product_area
            FROM retrievability_results r
            JOIN queries q ON q.id = r.query_id
        """, conn)
        conn.close()
        return df
    except Exception as e:
        st.error(f"Error loading retrievability results: {e}")
        return pd.DataFrame()


# Get the last modification time of the db to force cache invalidation if it changes
db_path = "discussions.db"
last_updated = os.path.getmtime(db_path) if os.path.exists(db_path) else 0
df = load_data(ttl_hash=last_updated)

if df.empty:
    st.warning("No data found. Please run the scraper first (or the analysis script).")
else:
    # Tabs for different views
    tab1, tab2, tab3 = st.tabs(["General Dashboard", "Topic Explorer", "Query Bank"])

    with tab1:
        # Filters
        st.sidebar.header("Filters")
        
        filtered_df = df.copy()

        # Platform Filter
        if "platform" in filtered_df.columns:
            platforms = ["All"] + sorted(filtered_df["platform"].dropna().unique().tolist())
            selected_platform = st.sidebar.selectbox("Platform", platforms)
            if selected_platform != "All":
                filtered_df = filtered_df[filtered_df["platform"] == selected_platform]

        # Sub-source Filter
        if "sub_source" in filtered_df.columns:
            # Filter sub-sources based on selected platform if applicable
            available_sub_sources = filtered_df["sub_source"].dropna().unique().tolist()
            sub_sources = ["All"] + sorted(available_sub_sources)
            selected_sub_source = st.sidebar.selectbox("Sub-source (Board/Subreddit)", sub_sources)
            if selected_sub_source != "All":
                filtered_df = filtered_df[filtered_df["sub_source"] == selected_sub_source]

        # Search
        search_term = st.sidebar.text_input("Search (Title/Content)")
        if search_term:
            filtered_df = filtered_df[
                filtered_df["title"].str.contains(search_term, case=False, na=False) | 
                filtered_df["content"].str.contains(search_term, case=False, na=False)
            ]

        # Category Filter (if analyzed)
        if "category" in filtered_df.columns:
            categories = ["All"] + sorted(filtered_df["category"].dropna().unique().tolist())
            selected_category = st.sidebar.selectbox("Category", categories)
            if selected_category != "All":
                filtered_df = filtered_df[filtered_df["category"] == selected_category]

        # Product Area Filter (if analyzed)
        if "product_area" in filtered_df.columns:
            products = ["All"] + sorted(filtered_df["product_area"].dropna().unique().tolist())
            selected_product = st.sidebar.selectbox("Product Area", products)
            if selected_product != "All":
                filtered_df = filtered_df[filtered_df["product_area"] == selected_product]

        # Intent Filter (if analyzed)
        if "intent" in filtered_df.columns:
            intents = ["All"] + sorted(filtered_df["intent"].dropna().unique().tolist())
            selected_intent = st.sidebar.selectbox("User Intent", intents)
            if selected_intent != "All":
                filtered_df = filtered_df[filtered_df["intent"] == selected_intent]

        # Author Role Filter (if analyzed)
        if "author_role" in filtered_df.columns:
            roles = ["All"] + sorted(filtered_df["author_role"].dropna().unique().tolist())
            selected_role = st.sidebar.selectbox("Author Role", roles)
            if selected_role != "All":
                filtered_df = filtered_df[filtered_df["author_role"] == selected_role]

        # Metrics
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Discussions", len(filtered_df))
        col2.metric("Unique Authors", filtered_df["author"].nunique() if "author" in filtered_df.columns else 0)
        
        if "publish_date" in filtered_df.columns:
            latest_date = filtered_df["publish_date"].max()
            if pd.notnull(latest_date):
                col3.metric("Latest Post", latest_date.strftime("%Y-%m-%d"))

        # Analysis Metrics (if available)
        has_analysis = "sentiment" in filtered_df.columns
        if has_analysis:
            neg_sentiment = len(filtered_df[filtered_df["sentiment"] == "Negative"])
            total_count = len(filtered_df)
            percentage = (neg_sentiment / total_count) if total_count > 0 else 0
            col4.metric("Negative Sentiment", f"{neg_sentiment} ({percentage:.1%})")

        # Visualizations
        if not filtered_df.empty:
            st.subheader("Insights")
            
            # Row 1: Platform & Source Distribution
            r1c1, r1c2 = st.columns(2)
            with r1c1:
                if "platform" in filtered_df.columns:
                    fig_plat = px.pie(filtered_df, names="platform", title="Discussions by Platform", hole=0.4)
                    st.plotly_chart(fig_plat, use_container_width=True)
            with r1c2:
                if "sub_source" in filtered_df.columns:
                    # Top 10 sources
                    source_counts = filtered_df["sub_source"].value_counts().head(10).reset_index()
                    source_counts.columns = ["sub_source", "count"]
                    fig_source = px.bar(source_counts, x="sub_source", y="count", title="Top Data Sources", color="sub_source")
                    st.plotly_chart(fig_source, use_container_width=True)

            # Row 2: Analysis Charts (if available)
            if has_analysis:
                r2c1, r2c2 = st.columns(2)
                with r2c1:
                    if "product_area" in filtered_df.columns:
                        fig_prod = px.pie(filtered_df, names="product_area", title="Discussions by Product Area")
                        st.plotly_chart(fig_prod, use_container_width=True)
                
                with r2c2:
                    if "sentiment" in filtered_df.columns:
                        fig_sent = px.bar(filtered_df, x="sentiment", title="Sentiment Distribution", color="sentiment")
                        st.plotly_chart(fig_sent, use_container_width=True)

                # Row 3: Intent & Author Role
                r3c1, r3c2 = st.columns(2)
                with r3c1:
                    if "intent" in filtered_df.columns:
                        fig_intent = px.pie(filtered_df, names="intent", title="User Intent Distribution", hole=0.4)
                        st.plotly_chart(fig_intent, use_container_width=True)
                
                with r3c2:
                    if "author_role" in filtered_df.columns:
                        fig_role = px.pie(filtered_df, names="author_role", title="Author Role Distribution", hole=0.4)
                        st.plotly_chart(fig_role, use_container_width=True)

        # Display Data
        st.subheader("Discussions List")
        
        # Configure columns for display
        display_cols = ["platform", "sub_source", "title", "author", "publish_date", "reply_count", "url"]
        if has_analysis:
            display_cols.extend(["category", "product_area", "sentiment", "intent", "author_role"])
        
        display_cols = [c for c in display_cols if c in df.columns]
        
        st.info("💡 **Tip:** Click the checkbox on the left of a row to view discussion details below.")

        selection = st.dataframe(
            filtered_df[display_cols],
            column_config={
                "publish_date": st.column_config.DatetimeColumn("Date", format="D MMM YYYY"),
                "reply_count": st.column_config.NumberColumn("Replies"),
                "platform": "Platform",
                "sub_source": "Source",
                "url": st.column_config.LinkColumn("Link", display_text="Open")
            },
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row"
        )

        # Detail View
        st.subheader("Discussion Details")
        
        if selection.selection.rows:
            selected_row_index = selection.selection.rows[0]
            item = filtered_df.iloc[selected_row_index]
            
            st.markdown(f"### [{item['title']}]({item.get('url', '#')})")
            st.markdown(f"**Author:** {item.get('author', 'Unknown')} | **Date:** {item.get('publish_date', 'Unknown')}")
            
            if has_analysis:
                st.info(f"**Category:** {item.get('category')} | **Product:** {item.get('product_area')} | **Sentiment:** {item.get('sentiment')} | **Intent:** {item.get('intent')} | **Role:** {item.get('author_role')}")
                if "pain_points" in item and item["pain_points"]:
                    st.markdown("**Pain Points:**")
                    for pp in item["pain_points"]:
                        st.markdown(f"- {pp}")
                if "summary" in item:
                    st.markdown(f"**Summary:** {item['summary']}")

            with st.expander("Full Content", expanded=True):
                st.write(item.get("content", ""))

            replies_df = load_replies(item["id"])
            if not replies_df.empty:
                st.markdown(f"#### Replies ({len(replies_df)})")
                for _, reply in replies_df.iterrows():
                    with st.container(border=True):
                        st.markdown(f"**{reply.get('author', 'Unknown')}** · {reply.get('publish_date', '')}")
                        st.write(reply.get("content", ""))
            else:
                st.markdown("#### Replies (0)")
                st.caption("No replies found for this discussion.")
        else:
            st.info("Select the checkbox next to a discussion to view details.")

    with tab2:
        st.header("Topic Explorer")
        st.write("Deep dive into specific topics and see how different roles (Admins, Developers, End Users) are discussing them.")

        if "category" not in df.columns or "author_role" not in df.columns:
            st.warning("Please run the analysis first to generate topics and roles.")
        else:
            # 1. Select Topic
            topics = sorted(df["category"].dropna().unique().tolist())
            selected_topic = st.selectbox("Select a Topic to Explore", topics)
            
            topic_df = df[df["category"] == selected_topic]
            
            # 2. Role Distribution
            st.subheader(f"Who is talking about this?")
            role_counts = topic_df["author_role"].value_counts().reset_index()
            role_counts.columns = ["Role", "Count"]
            fig_role_dist = px.bar(role_counts, x="Role", y="Count", color="Role", title="Role Distribution for this Topic")
            st.plotly_chart(fig_role_dist, use_container_width=True)

            # 3. Perspective Matrix
            st.subheader("Perspective Matrix")
            
            def get_top_keywords(texts, top_n=5):
                words = []
                stopwords = set(['the', 'to', 'and', 'of', 'a', 'in', 'is', 'it', 'for', 'on', 'that', 'this', 'with', 'i', 'you', 'are', 'not', 'have', 'be', 'can', 'how', 'do', 'what', 'my', 'but', 'as', 'if', 'or', 'an', 'at', 'from', 'so', 'me', 'we', 'microsoft', 'copilot', '365', 'use', 'using', 'get', 'when', 'will', 'has', 'all', 'any', 'there', 'about', 'would', 'like', 'just', 'need', 'know', 'want', 'does', 'which', 'one', 'only', 'also', 'more', 'some', 'out', 'up', 'who', 'why', 'where', 'time', 'new', 'now', 'user', 'users', 'work', 'working', 'issue', 'problem', 'error', 'help', 'question', 'questions', 'thanks', 'please', 'hi', 'hello', 'hey', 'good', 'great', 'best', 'better', 'much', 'many', 'very', 'really', 'too', 'even', 'still', 'back', 'way', 'see', 'make', 'find', 'look', 'think', 'go', 'going', 'been', 'being', 'should', 'could', 'did', 'done', 'doing', 'say', 'said', 'says', 'tell', 'told', 'tells', 'ask', 'asked', 'asks', 'answer', 'answered', 'answers', 'reply', 'replied', 'replies', 'post', 'posted', 'posts', 'thread', 'threads', 'topic', 'topics', 'discussion', 'discussions', 'forum', 'forums', 'community', 'communities', 'site', 'sites', 'page', 'pages', 'web', 'website', 'websites', 'link', 'links', 'url', 'urls', 'http', 'https', 'www', 'com', 'org', 'net', 'edu', 'gov', 'mil', 'int', 'arpa', 'biz', 'info', 'name', 'pro', 'aero', 'coop', 'museum', 'mobi', 'travel', 'tel', 'cat', 'jobs', 'asia', 'xxx', 'yacht', 'tel', 'post', 'mail', 'email', 'gmail', 'yahoo', 'hotmail', 'outlook', 'live', 'msn', 'aol', 'icloud', 'me', 'mac', 'iphone', 'ipad', 'android', 'windows', 'linux', 'unix', 'macos', 'ios', 'chrome', 'firefox', 'safari', 'edge', 'opera', 'brave', 'vivaldi', 'tor', 'duckduckgo', 'google', 'bing', 'yahoo', 'baidu', 'yandex', 'ask', 'aol', 'wolframalpha', 'startpage', 'qwant', 'searchencrypt', 'searx', 'swisscows', 'gibiru', 'disconnect', 'yippy', 'lukol', 'metager', 'gigablast', 'oscobo', 'infinity', 'search', 'engine', 'engines', 'web', 'browser', 'browsers', 'internet', 'online', 'offline', 'connect', 'connection', 'connected', 'connecting', 'disconnect', 'disconnected', 'disconnecting', 'network', 'networks', 'networking', 'wifi', 'wi-fi', 'wireless', 'wired', 'ethernet', 'lan', 'wan', 'man', 'pan', 'san', 'can', 'dan', 'fan', 'gan', 'han', 'ian', 'jan', 'kan', 'lan', 'man', 'nan', 'oan', 'pan', 'qan', 'ran', 'san', 'tan', 'uan', 'van', 'wan', 'xan', 'yan', 'zan'])
                for text in texts:
                    # Simple tokenization
                    tokens = re.findall(r'\b[a-zA-Z]{3,}\b', str(text).lower())
                    words.extend([t for t in tokens if t not in stopwords])
                
                return Counter(words).most_common(top_n)

            col_admin, col_dev, col_user = st.columns(3)

            # IT Admin Column
            with col_admin:
                st.markdown("### 🛡️ IT Admin")
                admin_df = topic_df[topic_df["author_role"] == "IT Admin"]
                if not admin_df.empty:
                    keywords = get_top_keywords(admin_df["title"] + " " + admin_df["content"])
                    st.markdown("**Top Keywords:**")
                    st.write(", ".join([f"*{k[0]}*" for k in keywords]))
                    
                    st.markdown("**Sample Discussions:**")
                    for _, row in admin_df.head(5).iterrows():
                        st.markdown(f"- [{row['title']}]({row.get('url', '#')})")
                else:
                    st.write("No discussions found.")

            # Developer Column
            with col_dev:
                st.markdown("### 💻 Developer")
                dev_df = topic_df[topic_df["author_role"] == "Developer"]
                if not dev_df.empty:
                    keywords = get_top_keywords(dev_df["title"] + " " + dev_df["content"])
                    st.markdown("**Top Keywords:**")
                    st.write(", ".join([f"*{k[0]}*" for k in keywords]))
                    
                    st.markdown("**Sample Discussions:**")
                    for _, row in dev_df.head(5).iterrows():
                        st.markdown(f"- [{row['title']}]({row.get('url', '#')})")
                else:
                    st.write("No discussions found.")

            # End User Column
            with col_user:
                st.markdown("### 👤 End User")
                user_df = topic_df[topic_df["author_role"] == "End User"]
                if not user_df.empty:
                    keywords = get_top_keywords(user_df["title"] + " " + user_df["content"])
                    st.markdown("**Top Keywords:**")
                    st.write(", ".join([f"*{k[0]}*" for k in keywords]))

                    st.markdown("**Sample Discussions:**")
                    for _, row in user_df.head(5).iterrows():
                        st.markdown(f"- [{row['title']}]({row.get('url', '#')})")
                else:
                    st.write("No discussions found.")

            # --- Reply Intelligence ---
            st.subheader("Reply Intelligence")

            reply_stats = load_reply_stats(ttl_hash=last_updated)

            if reply_stats.empty:
                st.caption("No reply data available.")
            else:
                # Merge reply stats onto topic discussions
                topic_with_replies = topic_df.merge(
                    reply_stats, left_on="id", right_on="parent_id", how="left"
                )

                total_replies = int(topic_with_replies["agg_reply_count"].sum(skipna=True))
                threads_with_replies = int(topic_with_replies["agg_reply_count"].notna().sum())
                st.markdown(f"**{total_replies} replies** across **{threads_with_replies} discussions** in this topic")

                # Reply sentiment bar (keyword-based on reply text)
                if total_replies > 0:
                    all_reply_text = " ".join(
                        topic_with_replies["all_reply_text"].dropna().tolist()
                    ).lower()
                    neg_words = ["fail", "error", "bug", "broken", "issue", "problem", "slow", "crash", "stuck", "frustrat"]
                    pos_words = ["great", "love", "amazing", "helpful", "thanks", "good", "fixed", "resolved", "working"]
                    neg = sum(all_reply_text.count(w) for w in neg_words)
                    pos = sum(all_reply_text.count(w) for w in pos_words)
                    neu = max(total_replies - neg - pos, 0)
                    total_signals = neg + pos + neu or 1

                    sentiment_fig = px.bar(
                        x=["Negative", "Neutral", "Positive"],
                        y=[neg/total_signals*100, neu/total_signals*100, pos/total_signals*100],
                        color=["Negative", "Neutral", "Positive"],
                        color_discrete_map={"Negative": "#e74c3c", "Neutral": "#95a5a6", "Positive": "#2ecc71"},
                        labels={"x": "Sentiment", "y": "% of signal words"},
                        title="Reply Sentiment Signal",
                    )
                    st.plotly_chart(sentiment_fig, use_container_width=True)

                # Top reply keywords
                st.markdown("**Top keywords in replies:**")
                combined_reply_text = " ".join(
                    topic_with_replies["all_reply_text"].dropna().tolist()
                )
                if combined_reply_text.strip():
                    import re as _re
                    from sklearn.feature_extraction.text import TfidfVectorizer as _TV
                    cleaned = _re.sub(r'[^a-zA-Z\s]', '', combined_reply_text).lower()
                    try:
                        tv = _TV(stop_words='english', max_features=50)
                        tv.fit_transform([cleaned])
                        top_words = tv.get_feature_names_out()[:10]
                        st.write(", ".join(top_words))
                    except Exception:
                        st.caption("Not enough reply text for keyword extraction.")
                else:
                    st.caption("No reply text available for this topic.")

                # Resolution signal
                if threads_with_replies > 0:
                    def is_positive(text):
                        if not text:
                            return False
                        return any(w in str(text).lower() for w in ["fixed", "resolved", "working", "thanks", "solved"])

                    resolved = topic_with_replies["all_reply_text"].apply(is_positive).sum()
                    pct = int(resolved / threads_with_replies * 100)
                    st.metric("Threads showing resolution signal", f"{pct}%",
                              help="% of threads where replies contain words like 'fixed', 'resolved', 'working'")

    with tab3:
        st.header("Query Bank")
        st.write("Real customer queries extracted from community discussions, scored against your documentation.")

        queries_df = load_queries_df(ttl_hash=last_updated)
        retrievability_df = load_retrievability_df(ttl_hash=last_updated)

        if queries_df.empty:
            st.info("No queries yet. Click **Extract Queries** in the sidebar to get started.")
        else:
            # --- Summary metrics ---
            total_q = len(queries_df)
            tested_q = retrievability_df["query_id"].nunique() if not retrievability_df.empty else 0
            avg_top1 = retrievability_df[retrievability_df["rank"] == 1]["score"].mean() if not retrievability_df.empty else None

            col1, col2, col3 = st.columns(3)
            col1.metric("Total Queries", total_q)
            col2.metric("Queries Tested", tested_q)
            col3.metric("Avg Top-1 Score", f"{avg_top1:.3f}" if avg_top1 is not None else "—")

            # --- Method breakdown ---
            if "method" in queries_df.columns:
                method_counts = queries_df["method"].value_counts().reset_index()
                method_counts.columns = ["Method", "Count"]
                fig = px.bar(method_counts, x="Method", y="Count",
                             title="Queries by Extraction Method",
                             color="Method")
                st.plotly_chart(fig, use_container_width=True)

            # --- Query list ---
            st.subheader("Query List")
            search = st.text_input("Search queries", placeholder="filter by keyword...")
            filtered_q = queries_df
            if search:
                mask = queries_df["query_text"].str.contains(search, case=False, na=False)
                filtered_q = queries_df[mask]

            display_cols = ["query_text", "method", "product_area", "source_title"]
            display_cols = [c for c in display_cols if c in filtered_q.columns]
            q_selection = st.dataframe(
                filtered_q[display_cols].reset_index(drop=True),
                use_container_width=True,
                on_select="rerun",
                selection_mode="single-row"
            )

            # --- Query detail: top docs ---
            if q_selection.selection.rows and not retrievability_df.empty:
                selected_idx = q_selection.selection.rows[0]
                selected_q = filtered_q.iloc[selected_idx]
                query_id = selected_q["id"]

                st.subheader(f"Top docs for: *{selected_q['query_text']}*")
                if selected_q.get("source_title"):
                    st.caption(f"Source discussion: {selected_q['source_title']}")

                top_docs = retrievability_df[retrievability_df["query_id"] == query_id].sort_values("rank")
                if top_docs.empty:
                    st.info("This query hasn't been tested yet. Run the retrievability test.")
                else:
                    for _, row in top_docs.iterrows():
                        with st.container(border=True):
                            score_pct = f"{row['score']:.1%}"
                            st.markdown(f"**#{row['rank']}** — {row['doc_title']} `{score_pct}`")
                            st.caption(row["doc_path"])

            # --- Coverage gaps ---
            if not retrievability_df.empty:
                st.subheader("Coverage Gaps")
                st.write("Queries where the top-1 doc score is below 0.05 — likely missing or hard-to-find content.")
                top1 = retrievability_df[retrievability_df["rank"] == 1]
                gaps = top1[top1["score"] < 0.05][["query_text", "score", "product_area"]].copy()
                gaps["score"] = gaps["score"].round(4)
                if gaps.empty:
                    st.success("No significant coverage gaps found.")
                else:
                    st.dataframe(gaps.reset_index(drop=True), use_container_width=True)
