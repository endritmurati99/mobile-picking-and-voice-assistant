.PHONY: help setup up down logs seed test clean

SHELL := /bin/bash
-include .env
export

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup: ## Erstmalige Einrichtung
	@test -f .env || (cp .env.example .env && echo "⚠️  .env erstellt — Werte ausfüllen!" && exit 1)
	@echo "Baue Docker Images..."
	docker compose build
	@echo "✅ Setup fertig. Zertifikate: bash infrastructure/scripts/setup-certs.sh <LAN-IP>"

up: ## Stack starten
	docker compose up -d
	@echo "⏳ Warte auf Services..."
	@sleep 10
	@echo "✅ Stack läuft."

down: ## Stack stoppen
	docker compose down

logs: ## Logs anzeigen
	docker compose logs -f --tail=50

logs-backend: ## Backend-Logs
	docker compose logs -f --tail=50 backend

logs-odoo: ## Odoo-Logs
	docker compose logs -f --tail=50 odoo

seed: ## Seed-Daten laden
	python infrastructure/scripts/seed-odoo.py --url http://localhost:8069 --db $${ODOO_DB:-picking} --user $${ODOO_USER:-admin} --api-key $${ODOO_API_KEY}

test: ## Backend-Tests
	cd backend && python -m pytest tests/ -v

clean: ## Alles entfernen
	docker compose down -v --rmi local

shell-odoo: ## Odoo Shell
	docker compose exec odoo odoo shell -d $${ODOO_DB:-picking}

shell-db: ## PostgreSQL Shell
	docker compose exec db psql -U $${POSTGRES_USER:-odoo} -d $${ODOO_DB:-picking}
