import json
import re
import argparse
import sqlite3
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from collections import Counter

def load_data_from_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT d.*,
               GROUP_CONCAT(r.content, ' ') AS reply_content
        FROM discussions d
        LEFT JOIN replies r ON r.parent_id = d.id
        GROUP BY d.id
    """)
    rows = cursor.fetchall()
    data = [dict(row) for row in rows]
    conn.close()
    return data

def update_db_with_analysis(db_path, data):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Add columns if they don't exist
    try:
        cursor.execute("ALTER TABLE discussions ADD COLUMN analysis_category TEXT")
    except sqlite3.OperationalError:
        pass # Column likely exists
        
    try:
        cursor.execute("ALTER TABLE discussions ADD COLUMN analysis_product_area TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE discussions ADD COLUMN analysis_sentiment TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE discussions ADD COLUMN analysis_intent TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE discussions ADD COLUMN analysis_author_role TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE discussions ADD COLUMN analysis_cluster_id INTEGER")
    except sqlite3.OperationalError:
        pass

    # Update rows
    for item in data:
        if 'analysis' in item:
            analysis = item['analysis']
            cursor.execute("""
                UPDATE discussions 
                SET analysis_category = ?, 
                    analysis_product_area = ?, 
                    analysis_sentiment = ?,
                    analysis_intent = ?,
                    analysis_author_role = ?,
                    analysis_cluster_id = ?
                WHERE id = ?
            """, (
                analysis.get('category'),
                analysis.get('product_area'),
                analysis.get('sentiment'),
                analysis.get('intent'),
                analysis.get('author_role'),
                analysis.get('cluster_id'),
                item.get('id')
            ))
            
    conn.commit()
    conn.close()

def clean_text(text):
    if not text:
        return ""
    # Remove URLs
    text = re.sub(r'http\S+', '', text)
    # Remove special chars and numbers
    text = re.sub(r'[^a-zA-Z\s]', '', text)
    return text.lower()

def get_product_area(text):
    text = text.lower()
    products = {
        "excel": "Excel",
        "word": "Word",
        "powerpoint": "PowerPoint",
        "outlook": "Outlook",
        "teams": "Teams",
        "copilot studio": "Copilot Studio",
        "loop": "Loop",
        "onenote": "OneNote",
        "whiteboard": "Whiteboard",
        "admin": "Admin Center",
        "security": "Security",
        "compliance": "Compliance",
        "windows": "Windows",
        "power bi": "Power BI",
        "power automate": "Power Automate",
        "sharepoint": "SharePoint",
        "onedrive": "OneDrive",
        "viva": "Viva",
        "stream": "Stream",
        "yammer": "Yammer",
        "planner": "Planner",
        "lists": "Lists",
        "forms": "Forms"
    }
    
    for key, value in products.items():
        if key in text:
            return value
    return "General"

def analyze_sentiment_keyword(text):
    # Very basic keyword-based sentiment since we don't have a model
    text = text.lower()
    neg_words = ["fail", "error", "bug", "broken", "issue", "problem", "slow", "crash", "stuck", "hate", "useless", "frustrat"]
    pos_words = ["great", "love", "amazing", "helpful", "thanks", "good", "excellent", "awesome"]
    
    neg_count = sum(1 for w in neg_words if w in text)
    pos_count = sum(1 for w in pos_words if w in text)
    
    if neg_count > pos_count:
        return "Negative"
    elif pos_count > neg_count:
        return "Positive"
    else:
        return "Neutral"

def analyze_intent_keyword(text):
    text = text.lower()
    
    # Bug / Issue
    bug_keywords = ["error", "fail", "crash", "bug", "not working", "broken", "issue", "problem", "stuck", "glitch", "exception", "slow", "latency"]
    if any(w in text for w in bug_keywords):
        return "Bug/Issue"
        
    # Feature Request
    request_keywords = ["feature request", "please add", "wish", "missing", "would like", "should have", "suggestion", "idea", "feedback", "improve"]
    if any(w in text for w in request_keywords):
        return "Feature Request"
        
    # Pricing / Licensing
    pricing_keywords = ["price", "cost", "license", "subscription", "billing", "expensive", "cheap", "pay", "e3", "e5"]
    if any(w in text for w in pricing_keywords):
        return "Pricing/Licensing"

    # How-to / Question
    question_keywords = ["how to", "how do i", "can i", "is it possible", "where is", "help", "guide", "tutorial", "?"]
    if any(w in text for w in question_keywords):
        return "How-to/Question"
        
    return "General Discussion"

def analyze_author_role(text):
    text = text.lower()
    
    # Developer
    dev_keywords = ["api", "sdk", "code", "script", "json", "xml", "endpoint", "token", "auth", "react", "node", "c#", "python", "javascript", "graph api", "rest", "webhook", "bot", "framework", "library", "spfx", "csom", "pnp"]
    if any(w in text for w in dev_keywords):
        return "Developer"

    # IT Admin (Merged with IT Professional)
    admin_keywords = [
        "admin center", "tenant", "global admin", "permissions", "policy", "migration", "powershell", 
        "active directory", "entra", "compliance", "security", "audit", "users", "groups", "license", 
        "configure", "deploy", "provision",
        # IT Pro keywords merged in:
        "server", "network", "infrastructure", "hybrid", "on-prem", "sharepoint server", 
        "exchange server", "deployment", "configuration", "topology", "farm", "bandwidth", "latency"
    ]
    if any(w in text for w in admin_keywords):
        return "IT Admin"

    # End User (Heuristic: "How do I", "Where is", simple complaints)
    user_keywords = ["how do i", "where is", "button", "screen", "stopped working", "help", "tutorial", "guide", "confused", "can't find", "missing", "slow", "crash", "error message", "my app"]
    if any(w in text for w in user_keywords):
        return "End User"

    return "End User" # Default to End User as they are the most common source of feedback

def main():
    parser = argparse.ArgumentParser(description="Analyze discussion intents using local clustering.")
    parser.add_argument("--db", default="discussions.db", help="Input SQLite database path")
    parser.add_argument("--clusters", type=int, default=8, help="Number of clusters")
    args = parser.parse_args()

    print(f"Loading data from {args.db}...")
    try:
        data = load_data_from_db(args.db)
    except Exception as e:
        print(f"Error loading database: {e}")
        return

    if not data:
        print("No data found in database.")
        return
    
    # Prepare text for clustering
    documents = []
    valid_indices = []
    
    for i, item in enumerate(data):
        text = " ".join(filter(None, [
            str(item.get('title', '')),
            str(item.get('content', '')),
            str(item.get('reply_content', '') or '')
        ]))
        cleaned = clean_text(text)
        if len(cleaned) > 10:
            documents.append(cleaned)
            valid_indices.append(i)
            
    if not documents:
        print("Not enough data for clustering.")
        return

    print(f"Vectorizing {len(documents)} documents...")
    vectorizer = TfidfVectorizer(stop_words='english', max_features=1000)
    X = vectorizer.fit_transform(documents)
    
    # Adjust clusters if we have fewer documents than requested clusters
    n_clusters = min(args.clusters, len(documents))
    if n_clusters < args.clusters:
        print(f"Reducing clusters to {n_clusters} due to small dataset.")
    
    print(f"Clustering into {n_clusters} topics...")
    kmeans = KMeans(n_clusters=n_clusters, random_state=42)
    kmeans.fit(X)
    
    # Get cluster keywords
    print("Identifying cluster themes...")
    feature_names = vectorizer.get_feature_names_out()
    cluster_names = {}
    
    for i in range(n_clusters):
        center = kmeans.cluster_centers_[i]
        top_ind = center.argsort()[:-6:-1]
        keywords = [feature_names[ind] for ind in top_ind]
        cluster_names[i] = f"Topic: {', '.join(keywords)}"
        print(f"Cluster {i}: {', '.join(keywords)}")

    # Assign results back to data
    print("Tagging data...")
    
    # Create a map of doc_idx -> cluster_id for quick lookup
    doc_to_cluster = {doc_idx: kmeans.labels_[idx] for idx, doc_idx in enumerate(valid_indices)}

    for i, item in enumerate(data):
        full_text = " ".join(filter(None, [
            str(item.get('title', '')),
            str(item.get('content', '')),
            str(item.get('reply_content', '') or '')
        ]))
        
        # Determine cluster info
        if i in doc_to_cluster:
            cluster_id = doc_to_cluster[i]
            category = cluster_names[cluster_id]
            cid = int(cluster_id)
        else:
            category = "General / Short Content"
            cid = -1

        analysis = {
            "category": category,
            "cluster_id": cid,
            "product_area": get_product_area(full_text),
            "sentiment": analyze_sentiment_keyword(full_text),
            "intent": analyze_intent_keyword(full_text),
            "author_role": analyze_author_role(full_text),
            "pain_points": [], 
            "summary": item.get('title', '') 
        }
        
        item['analysis'] = analysis

    print(f"Saving analysis back to {args.db}...")
    update_db_with_analysis(args.db, data)
        
    print(f"Analysis complete. Database updated.")

if __name__ == "__main__":
    main()
