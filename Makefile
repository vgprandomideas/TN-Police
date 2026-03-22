.PHONY: init seed api worker frontend docker-up docker-down test

init:
	python -m db.init_db

seed:
	python scripts/seed_demo.py

api:
	uvicorn app.main:app --reload

worker:
	python scripts/run_worker.py

frontend:
	streamlit run frontend/frontend_app.py

docker-up:
	docker compose up --build

docker-down:
	docker compose down -v

test:
	python -m compileall app db services scripts frontend adapters
