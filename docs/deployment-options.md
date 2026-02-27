# Deployment Options

## Current status: localhost only

This app runs locally (`streamlit run app.py`). The SQLite database, scraped data, and Azure OpenAI credentials stay on the local machine. This is the right choice for a proof of concept — no external exposure, no infrastructure to maintain.

## Why not GitHub Pages

GitHub Pages only serves static files. This app requires a running Python server (SQLite reads/writes, subprocess execution for scrapers, live Azure OpenAI API calls) and cannot be made static without rewriting the core architecture.

## Options when ready to scale beyond localhost

| Option | When to use | Notes |
|--------|-------------|-------|
| **Shared localhost** | Small team, same office | Each person runs `streamlit run app.py` against a shared `discussions.db` (e.g., on a network drive or synced via OneDrive) |
| **Azure App Service + Azure AD** | Remote access needed, enterprise security | Hosts the app on Azure with Microsoft account authentication — only your team can log in. Natural fit since Azure OpenAI is already in use. |
| **Docker on internal VM** | Behind-VPN access | Containerize the app, run on a company VM. Accessible inside the corporate network only. |
| **Streamlit Community Cloud** | Public demos only | Avoid for internal use — scraped discussion data and API keys would reside on a third-party server. |

## Before any hosted deployment

Complete the `db.py` extraction plan first (`docs/plans/db-extraction.md`). It cleans up `app.py` enough that containerizing becomes straightforward, and removes the SQLite connection patterns that would need to change if migrating to a hosted database later.
