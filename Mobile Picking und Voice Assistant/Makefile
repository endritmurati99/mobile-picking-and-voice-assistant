.PHONY: help setup install-backend-deps install-ui-deps build-all build-backend build-odoo up down logs logs-backend logs-odoo seed test test-infra test-n8n test-pwa test-odoo test-all test-ui test-visual-diff-update test-a11y test-api test-n8n-api load-test verify-workflows verify-code verify-stack verify clean shell-odoo shell-db

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

install-ui-deps: ## Node-Abhaengigkeiten fuer die e2e-Suite installieren (Playwright)
	npm ci
	npx playwright install chromium

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
	python infrastructure/scripts/seed-odoo.py --url http://localhost:8069 --db $${ODOO_DB:-masterfischer_o19} --user $${ODOO_USER:-admin} --api-key $${ODOO_API_KEY}

test: ## Backend-Tests
	cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio tests/ -v

test-infra: ## Tests der Infrastruktur-Skripte (Zertifikate, Seed, Rauchtests)
	cd backend && PYTHONPATH=.deps python -m pytest -p pytest_asyncio ../infrastructure/tests -v

test-n8n: ## Vertragstests der n8n-Kette (Fingerprint-Paritaet, Credential-Provisionierung)
	node --test n8n/tests/*.test.mjs

test-pwa: ## Modultests der PWA (Voice-Laufzeit, reines Node, kein Browser)
	node --test pwa/js/tests/*.test.mjs

test-odoo: ## Tests der eigenen Odoo-Module gegen eine WEGWERF-Datenbank
	@echo "Legt die Datenbank $${ODOO_TEST_DB:-picking_test} neu an und verwirft sie danach."
	docker compose run --rm -e ODOO_TEST_DB=$${ODOO_TEST_DB:-picking_test} odoo \
		odoo -d $${ODOO_TEST_DB:-picking_test} \
		-i picking_assistant_core,picking_assistant_integration,quality_alert_custom \
		--test-enable --stop-after-init --log-level=test

test-all: ## Alle ausfuehrbaren Testsuiten nacheinander
	$(MAKE) test
	$(MAKE) test-infra
	$(MAKE) test-n8n
	$(MAKE) test-pwa

test-ui: ## e2e-Suite (Playwright, braucht Browser via install-ui-deps)
	npx playwright test

test-visual-diff-update: ## Visuelle Baselines der e2e-Suite neu erzeugen
	npx playwright test --update-snapshots

test-a11y: ## Nur die Accessibility-Suite (axe-core)
	npx playwright test e2e/a11y.spec.js

test-api: ## API-Rauchtest
	python infrastructure/scripts/test-api.py

test-n8n-api: ## n8n Public API mit API-Key pruefen
	python infrastructure/scripts/test-n8n-api.py

load-test: ## 100 Quality-Alert-Requests gegen laufenden Stack (Lasttest)
	python infrastructure/scripts/load-test-quality-alerts.py --count $${LOAD_TEST_COUNT:-100} --concurrency $${LOAD_TEST_CONCURRENCY:-10}

verify-workflows: ## n8n-Workflow-Vertraege gegen Backend-Webhooks pruefen
	python infrastructure/scripts/verify-workflows.py

verify-code: ## Schneller Code-Check ohne laufenden Stack
	$(MAKE) test-all

verify-stack: ## Stack-Check gegen laufende lokale Instanz
	$(MAKE) test-api

verify: ## Voller Verify-Lauf: Tests plus API-Rauchtest
	$(MAKE) verify-code
	$(MAKE) verify-workflows
	$(MAKE) verify-stack

clean: ## Alles entfernen
	docker compose down -v --rmi local

shell-odoo: ## Odoo Shell
	docker compose exec odoo odoo shell -d $${ODOO_DB:-masterfischer_o19}

shell-db: ## PostgreSQL Shell
	docker compose exec db psql -U $${POSTGRES_USER:-odoo} -d $${ODOO_DB:-masterfischer_o19}
