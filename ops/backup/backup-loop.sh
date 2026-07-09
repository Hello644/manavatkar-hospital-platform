#!/bin/sh
# Day-one PostgreSQL backup loop. POSIX sh has no `pipefail`, so we must NOT rely
# on `pg_dump | gzip` — a failed dump still yields a valid (empty) gzip and the
# pipeline reports success, silently shipping a corrupt backup and then pruning
# the good ones. Instead: dump to a temp file, check pg_dump's own exit status,
# validate the result is non-empty, publish atomically, and only prune old
# backups after a verified success.
set -eu

mkdir -p /backups

while true; do
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  target="/backups/${POSTGRES_DB}_${stamp}.sql.gz"
  tmp_sql="/backups/.${POSTGRES_DB}_${stamp}.sql.partial"
  tmp_gz="${target}.partial"
  echo "Starting PostgreSQL backup: ${target}"

  if PGPASSWORD="${POSTGRES_PASSWORD}" pg_dump \
      --host=db \
      --username="${POSTGRES_USER}" \
      --dbname="${POSTGRES_DB}" \
      --format=plain \
      --no-owner \
      --no-acl > "${tmp_sql}"; then
    gzip -c "${tmp_sql}" > "${tmp_gz}"
    rm -f "${tmp_sql}"
    if [ -s "${tmp_gz}" ] && gzip -t "${tmp_gz}" 2>/dev/null; then
      mv "${tmp_gz}" "${target}"
      echo "Backup complete: ${target}"
      # Prune old backups ONLY after a verified-good new one exists.
      find /backups -name "${POSTGRES_DB}_*.sql.gz" -type f \
        -mtime +"${BACKUP_RETENTION_DAYS}" -delete
    else
      echo "ERROR: backup archive missing or corrupt; keeping previous backups" >&2
      rm -f "${tmp_gz}"
    fi
  else
    echo "ERROR: pg_dump failed; previous backups retained, no prune performed" >&2
    rm -f "${tmp_sql}" "${tmp_gz}" 2>/dev/null || true
  fi

  sleep "${BACKUP_INTERVAL_SECONDS}"
done
