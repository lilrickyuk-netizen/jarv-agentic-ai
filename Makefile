.PHONY: help dev up down build logs clean test

help:
	@echo "JARV Docker Commands:"
	@echo "  make dev     - Start services in development mode with hot reload"
	@echo "  make up      - Start services in production mode"
	@echo "  make down    - Stop all services"
	@echo "  make build   - Build all Docker images"
	@echo "  make logs    - View logs from all services"
	@echo "  make clean   - Remove all containers, volumes, and images"
	@echo "  make test    - Run tests in containers"

dev:
	docker-compose -f docker-compose.yml -f docker-compose.dev.yml up

up:
	docker-compose up -d

down:
	docker-compose down

build:
	docker-compose build

rebuild:
	docker-compose build --no-cache

logs:
	docker-compose logs -f

clean:
	docker-compose down -v --rmi all --remove-orphans

restart:
	docker-compose restart

ps:
	docker-compose ps

backend-shell:
	docker-compose exec backend bash

dashboard-shell:
	docker-compose exec dashboard sh

worker-shell:
	docker-compose exec worker bash

db-shell:
	docker-compose exec postgres psql -U jarv -d jarv

redis-shell:
	docker-compose exec redis redis-cli

test:
	docker-compose exec backend pytest
	docker-compose exec worker pytest
