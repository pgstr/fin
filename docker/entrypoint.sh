#!/bin/sh
set -eu

mkdir -p /data /backups
if ! chown finanzplaner:finanzplaner /data /backups 2>/dev/null; then
  echo "warning: volume ownership could not be changed; continuing with mounted permissions" >&2
fi

case "${1:-serve}" in
  serve)
    gosu finanzplaner alembic upgrade head
    exec gosu finanzplaner finanzplaner serve --host 0.0.0.0 --port 8080
    ;;
  backup)
    exec gosu finanzplaner finanzplaner backup create
    ;;
  backup-list)
    exec gosu finanzplaner finanzplaner backup list
    ;;
  *)
    exec gosu finanzplaner "$@"
    ;;
esac
