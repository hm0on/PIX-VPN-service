.PHONY: help up down logs ps restart build migrate makemigration shell-backend shell-bot shell-db psql redis-cli test-backend lint-backend lint-admin admin-dev admin-build clean

DC := docker compose -f infra/docker-compose.yml --env-file .env

help:
	@echo "VPN_PIX_bot — Stage 1"
	@echo ""
	@echo "  make up                — поднять все сервисы (-d)"
	@echo "  make down              — остановить и удалить контейнеры"
	@echo "  make build             — пересобрать образы"
	@echo "  make logs s=backend    — логи сервиса (backend|bot|worker|admin|nginx|postgres|redis)"
	@echo "  make ps                — список контейнеров"
	@echo "  make restart s=backend — рестарт сервиса"
	@echo ""
	@echo "  make migrate                       — применить миграции"
	@echo "  make makemigration m=\"add x\"      — создать новую миграцию"
	@echo ""
	@echo "  make shell-backend / shell-bot     — bash в контейнере"
	@echo "  make psql / redis-cli              — клиенты БД"
	@echo ""
	@echo "  make test-backend                  — тесты"
	@echo "  make lint-backend / lint-admin     — линтеры"
	@echo "  make admin-dev / admin-build       — фронт локально"

up:
	$(DC) up -d

down:
	$(DC) down

build:
	$(DC) build

logs:
	$(DC) logs -f $(s)

ps:
	$(DC) ps

restart:
	$(DC) restart $(s)

migrate:
	$(DC) exec backend alembic upgrade head

makemigration:
	$(DC) exec backend alembic revision --autogenerate -m "$(m)"

shell-backend:
	$(DC) exec backend bash

shell-bot:
	$(DC) exec bot bash

shell-db:
	$(DC) exec postgres bash

psql:
	$(DC) exec postgres psql -U $${POSTGRES_USER:-vpn_pix} -d $${POSTGRES_DB:-vpn_pix}

redis-cli:
	$(DC) exec redis redis-cli -a $${REDIS_PASSWORD}

test-backend:
	$(DC) exec backend pytest -v

lint-backend:
	cd backend && ruff check . && mypy app

lint-admin:
	cd admin && npm run lint

admin-dev:
	cd admin && npm run dev

admin-build:
	cd admin && npm run build

clean:
	$(DC) down -v
	rm -rf admin/node_modules admin/dist
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
