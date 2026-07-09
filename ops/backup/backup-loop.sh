#!/bin/sh
set -eu

mkdir -p /backups

while true; do
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  target="/backups/${POSTGRES_DB}_${stamp}.sql.gz"
  echo "Starting PostgreSQL backup: ${target}"
  PGPASSWORD="${POSTGRES_PASSWORD}" pg_dump \
    --host=db \
    --username="${POSTGRES_USER}" \
    --dbname="${POSTGRES_DB}" \
    --format=plain \
    --no-owner \
    --no-acl \
    | gzip > "${target}"
  echo "Backup complete: ${target}"

  find /backups -name "${POSTGRES_DB}_*.sql.gz" -type f -mtime +"${BACKUP_RETENTION_DAYS}" -delete
  sleep "${BACKUP_INTERVAL_SECONDS}"
done

