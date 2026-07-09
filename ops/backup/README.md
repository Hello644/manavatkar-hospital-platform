# Backup Scaffold

Phase 0 includes a simple PostgreSQL dump sidecar so backups exist from the first container run.

Production deployment still needs the plan's full backup design before go-live:

- pgBackRest nightly full backup plus WAL archiving to the second internal SSD.
- Local encrypted file backup for uploads and attendance photos.
- Encrypted restic cloud backup excluding biometric templates and punch photos.
- Standby restore drill on the second mini-PC.

The current sidecar writes compressed SQL dumps into the `backup_data` Docker volume and deletes old dumps after `BACKUP_RETENTION_DAYS`.

