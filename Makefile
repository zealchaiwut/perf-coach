.PHONY: migrate lint-yaml regen-golden

migrate:
	alembic revision --autogenerate -m "$(MSG)"

lint-yaml:
	yamllint render.yaml

regen-golden:
	python scripts/regen_golden.py
