import json
import os
import sys
import argparse
import time
import sqlite3
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

try:
    from openai import AzureOpenAI
except ImportError:
    print("Error: 'openai' library not found. Please install it using 'pip install openai'")
    sys.exit(1)

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, **kwargs): return iterable

def load_data_from_db(db_path, limit=0):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = "SELECT * FROM discussions"
    if limit > 0:
        query += f" LIMIT {limit}"
    cursor.execute(query)
    rows = cursor.fetchall()
    data = [dict(row) for row in rows]

    # Attach top 3 replies per discussion for richer LLM context
    for item in data:
        cursor.execute("""
            SELECT content FROM replies
            WHERE parent_id = ?
            ORDER BY publish_date
            LIMIT 3
        """, (item['id'],))
        item['top_replies'] = [r['content'] for r in cursor.fetchall()]

    conn.close()
    return data

def update_db_with_analysis(db_path, item_id, analysis):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Add columns if they don't exist
    columns = [
        "analysis_category", "analysis_product_area", "analysis_sentiment", 
        "analysis_intent", "analysis_summary", "analysis_pain_points"
    ]
    
    for col in columns:
        try:
            cursor.execute(f"ALTER TABLE discussions ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass # Column likely exists

    # Update row
    cursor.execute("""
        UPDATE discussions 
        SET analysis_category = ?, 
            analysis_product_area = ?, 
            analysis_sentiment = ?,
            analysis_intent = ?,
            analysis_summary = ?,
            analysis_pain_points = ?
        WHERE id = ?
    """, (
        analysis.get('category'),
        analysis.get('product_area'),
        analysis.get('sentiment'),
        analysis.get('category'), # Mapping category to intent for consistency with local script
        analysis.get('summary'),
        json.dumps(analysis.get('pain_points', [])),
        item_id
    ))
            
    conn.commit()
    conn.close()

def analyze_intent(client, discussion, deployment_name):
    """
    Analyzes the customer intent and pain points of a discussion using an LLM.
    """
    title = discussion.get('title', '')
    content = discussion.get('content', '')
    
    # Skip empty content
    if not content or len(content) < 10:
        return None

    system_prompt = "You are an expert product analyst for Microsoft 365 Copilot. Your goal is to identify customer pain points and categorize feedback."

    top_replies = discussion.get('top_replies', [])
    replies_text = ""
    if top_replies:
        formatted = "\n".join(f"  - {r}" for r in top_replies if r and len(r.strip()) > 5)
        if formatted:
            replies_text = f"\nTop replies:\n{formatted}"

    user_prompt = f"""
    Analyze the following customer discussion thread including its replies.

    Title: {title}
    Post: {content}{replies_text}

    Provide the output in JSON format with the following keys:
    - "category": (e.g., "Bug/Issue", "Feature Request", "How-to/Question", "Pricing/Licensing", "General Discussion")
    - "product_area": (e.g., "Excel", "Outlook", "Teams", "PowerPoint", "Admin Center", "Copilot Studio", "General")
    - "pain_points": A list of specific struggles or issues mentioned across the post AND replies (max 3).
    - "sentiment": Overall sentiment considering both post and replies (e.g., "Positive", "Neutral", "Negative")
    - "summary": A concise one-sentence summary of the core issue and how it was received.
    """

    try:
        response = client.chat.completions.create(
            model=deployment_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0,
            response_format={ "type": "json_object" }
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"Error analyzing item '{title[:30]}...': {e}")
        return None

def main():
    parser = argparse.ArgumentParser(description="Analyze discussion intents using Azure OpenAI.")
    parser.add_argument("--db", default="discussions.db", help="Input SQLite database path")
    parser.add_argument("--limit", type=int, default=10, help="Number of items to analyze (default: 10). Set to 0 for all.")
    args = parser.parse_args()

    # Check for Azure OpenAI Environment Variables
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

    if not all([api_key, endpoint, deployment_name]):
        print("Error: Missing Azure OpenAI environment variables.")
        print("Please set: AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT_NAME")
        return

    if not os.path.exists(args.db):
        print(f"Error: {args.db} not found.")
        return

    print(f"Loading data from {args.db}...")
    data = load_data_from_db(args.db, args.limit)
    
    print(f"Processing {len(data)} items...")

    client = AzureOpenAI(
        api_key=api_key,
        api_version=api_version,
        azure_endpoint=endpoint
    )
    
    print("Starting analysis...")
    
    for item in tqdm(data, desc="Analyzing"):
        analysis = analyze_intent(client, item, deployment_name)
        if analysis:
            update_db_with_analysis(args.db, item['id'], analysis)
        # Small sleep to avoid aggressive rate limiting if needed
        # time.sleep(0.1) 

    print(f"\nAnalysis complete.")

if __name__ == "__main__":
    main()
