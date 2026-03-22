.PHONY: help setup install-backend-deps install-ui-deps build-all build-backend build-odoo up down logs seed test test-ui test-api verify-code verify-ui verify-workflows verify-stack verify clean

SHELL := /bin/bash
-include .env
export

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup: ## Erstmalige Einrichtung
	@test -f .env || (cp .env.example .env && echo "WARNUNG: .env erstellt - Werte ausfuellen!" && exit 1)
	@echo "Baue Docker Images..."
	docker compose build
	@echo "Setup fertig. Zertifikate: bash infrastructure/scripts/setup-certs.sh <LAN-IP>"

install-backend-deps: ## Lokale Python-Abhaengigkeiten fuer Backend-Tests installieren
	cd backend && python -m pip install --target .deps -r requirements-dev.txt

install-ui-deps: ## Playwright und Browser-Abhaengigkeiten installieren
	npm.cmd install
	npx.cmd playwright install chromium

build-all: ## Alle Docker Images bauen
	docker compose build

build-backend: ## Nur Backend Image bauen
	docker compose build backend

build-odoo: ## Nur Odoo Image bauen
	docker compose build odoo

up: ## Stack starten
	docker compose up -d
	@echo "Warte auf Services..."
	@sleep 10
	@echo "Stack laeuft."

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
	cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -v

test-ui: ## Browser-Tests fuer die PWA
	npx.cmd playwright test

test-api: ## API-Rauchtest
	python infrastructure/scripts/test-api.py

verify-workflows: ## n8n-Workflow-Vertraege gegen Backend-Webhooks pruefen
	python infrastructure/scripts/verify-workflows.py

verify-code: ## Schneller Code-Check ohne laufenden Stack
	$(MAKE) test

verify-ui: ## UI-Check der PWA ueber Playwright
	$(MAKE) test-ui

verify-stack: ## Stack-Check gegen laufende lokale Instanz
	$(MAKE) test-api

verify: ## Voller Verify-Lauf: Tests plus API-Rauchtest
	$(MAKE) verify-code
	$(MAKE) verify-ui
	$(MAKE) verify-workflows
	$(MAKE) verify-stack

clean: ## Alles entfernen
	docker compose down -v --rmi local

shell-odoo: ## Odoo Shell
	docker compose exec odoo odoo shell -d $${ODOO_DB:-picking}

shell-db: ## PostgreSQL Shell
	docker compose exec db psql -U $${POSTGRES_USER:-odoo} -d $${ODOO_DB:-picking}
