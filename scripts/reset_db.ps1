# Wipes all app tables but keeps the Postgres volume.
# Useful when you want to start fresh and re-test memory storage.

$DB_SERVICE = if ($env:DB_SERVICE) { $env:DB_SERVICE } else { "db" }
$DB_NAME    = if ($env:DB_NAME) { $env:DB_NAME } else { "ctf_smasher" }
$DB_USER    = if ($env:DB_USER) { $env:DB_USER } else { "ctf" }

$SQL = "TRUNCATE TABLE conversations, findings, flags, successful_runs, embeddings, sessions RESTART IDENTITY CASCADE;"

Write-Host "[reset_db] Truncating tables in $DB_SERVICE/$DB_NAME ..."
docker compose exec -T $DB_SERVICE psql -U $DB_USER -d $DB_NAME -c $SQL
Write-Host "[reset_db] Done."
