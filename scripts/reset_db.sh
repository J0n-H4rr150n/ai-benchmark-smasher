#!/usr/bin/env sh
set -eu

# Wipes all app tables but keeps the Postgres volume.
# Useful when you want to start fresh and re-test memory storage.

DB_SERVICE="${DB_SERVICE:-db}"
DB_NAME="${DB_NAME:-ctf_smasher}"
DB_USER="${DB_USER:-ctf}"

SQL="TRUNCATE TABLE conversations, findings, flags, successful_runs, embeddings, sessions RESTART IDENTITY CASCADE;"

echo "[reset_db] Truncating tables in $DB_SERVICE/$DB_NAME ..."
docker compose exec -T "$DB_SERVICE" psql -U "$DB_USER" -d "$DB_NAME" -c "$SQL"
echo "[reset_db] Done."
