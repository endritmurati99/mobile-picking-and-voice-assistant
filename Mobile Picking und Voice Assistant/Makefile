.PHONY: help setup build-all build-backend build-odoo up down logs logs-backend logs-odoo seed clean shell-odoo shell-db

SHELL := /bin/bash
-include .env
export

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup: ## Erstmalige Einrichtung
	@test -f .env || (echo "FEHLER: lokale .env fehlt; mit 'install -m 600 /dev/null .env' anlegen und Werte setzen." >&2; exit 1)
	@echo "Baue Docker Images..."
	docker compose build
	@echo "Setup fertig. Zertifikate: bash infrastructure/scripts/setup-certs.sh <LAN-IP>"

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

clean: ## Alles entfernen
	docker compose down -v --rmi local

shell-odoo: ## Odoo Shell
	docker compose exec odoo odoo shell -d $${ODOO_DB:-masterfischer_o19}

shell-db: ## PostgreSQL Shell
	docker compose exec db psql -U $${POSTGRES_USER:-odoo} -d $${ODOO_DB:-masterfischer_o19}
