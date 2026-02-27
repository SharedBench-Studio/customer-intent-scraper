# Query Extraction: LLM Upgrade Plan (Option B)

> Status: DEFERRED — implement when Azure OpenAI credentials are available.
> Current implementation: see `extract_queries.py` (rule-based, Option A).

## Goal

Replace or augment rule-based extraction with GPT-4o reformulation for richer,
more accurate search queries — especially for implicit-intent posts that have no
explicit `?`.

## How to activate

### Step 1: Confirm credentials in `.env`

```
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o
AZURE_OPENAI_API_VERSION=2024-02-15-preview
```

Run `analyze_intent.py` on a few rows first to confirm credentials work.

### Step 2: Add `--use-llm` flag to `extract_queries.py`

Add to `main()` argument parser:
```python
parser.add_argument("--use-llm", action="store_true",
                    help="Use Azure OpenAI to reformulate implicit queries")
```

### Step 3: Add `reformulate_with_llm(discussion, client, deployment)` function

```python
def reformulate_with_llm(discussion, client, deployment):
    title = discussion.get("title", "")
    content = (discussion.get("content", "") or "")[:500]  # cap tokens
    prompt = f"""Given this customer discussion, write 1-3 search queries
this person would type into a help search to find documentation.
Return ONLY a JSON array of strings.

Title: {title}
Content: {content}"""

    try:
        response = client.chat.completions.create(
            model=deployment,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"}
        )
        import json
        data = json.loads(response.choices[0].message.content)
        # Handle both {"queries": [...]} and bare [...]
        if isinstance(data, list):
            return data
        return data.get("queries", [])
    except Exception as e:
        print(f"LLM reformulation failed for {discussion.get('id')}: {e}")
        return []
```

### Step 4: Use LLM only for `title_implicit` results

In `main()`, after rule-based extraction, if `--use-llm`:

```python
if args.use_llm:
    from openai import AzureOpenAI
    from dotenv import load_dotenv
    load_dotenv()
    client = AzureOpenAI(
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
    )
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")

    implicit = [d for d in discussions
                if all(q["method"] != "title_implicit"
                       or d["id"] != q["source_id"]
                       for q in all_queries)]
    print(f"  Reformulating {len(implicit)} implicit discussions via LLM...")
    for d in implicit:
        for text in reformulate_with_llm(d, client, deployment):
            all_queries.append({
                "query_text": text,
                "source_id": d["id"],
                "method": "llm_reformulation",
                "product_area": d.get("analysis_product_area"),
            })
```

### Step 5: Add `method = 'llm_reformulation'` to dashboard filter

In `app.py` Query Bank tab, the method breakdown chart already reads from the
`method` column — no changes needed. The new method will appear automatically.

## Estimated API cost

~1,000 discussions × ~300 tokens each = ~300K tokens
At gpt-4o pricing (~$5/1M input tokens) ≈ $1.50 for a full run.
