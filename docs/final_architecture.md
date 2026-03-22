# Final Architecture

## Stack
- FastAPI backend
- Streamlit operational console
- SQLAlchemy ORM
- PostgreSQL for production, SQLite fallback for demo
- Background worker for queue processing
- JWT authentication
- Docker Compose infrastructure with Postgres, API, worker, frontend, and Nginx reverse proxy

## Major capability blocks
- Public metrics and command dashboard
- Complaints, incidents, cases, assignments, comments, and timelines
- Entity graph with links, graph snapshots, graph insights, fusion workbench, and similarity hits
- Watchlists, watchlist hits, suspect dossiers, evidence registry, and evidence-integrity logs
- Routing rules, SLA tracking, officer workload, station KPIs, and briefing registry
- Court hearing tracker, prosecution packets, custody logs, medical checks, prison movements
- Notifications, export jobs, war-room snapshots, bookmarks, and narrative briefs

## Data boundary
This bundle is feature-complete for an MVP / internal prototype. It still respects the public-data boundary:
- public statewide metrics are seeded where available
- privileged police systems are represented by stubs, registry items, and synthetic operational flows
- real production use would need sanctioned integrations and legal approvals
