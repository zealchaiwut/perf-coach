.PHONY: migrate

migrate:
	alembic revision --autogenerate -m "$(MSG)"
