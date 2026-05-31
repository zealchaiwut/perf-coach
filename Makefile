.PHONY: migrate lint-yaml

migrate:
	alembic revision --autogenerate -m "$(MSG)"

lint-yaml:
	yamllint render.yaml
