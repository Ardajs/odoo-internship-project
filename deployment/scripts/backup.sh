#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

MODE="${CONSISTENCY_MODE:-stop}"
case "${1:-}" in
    ""|--consistent) MODE="stop" ;;
    --online) MODE="online" ;;
    -h|--help)
        cat <<'EOF'
Usage: sudo backup.sh [--consistent|--online]

--consistent  Stop Odoo while pg_dump and filestore archive are produced.
              This is the default and gives a matched DB+filestore set.
--online      Keep Odoo running. This can produce a DB/filestore timing gap and
              must only be used with an external snapshot/maintenance design.
EOF
        exit 0
        ;;
    *) die "Unknown option: $1" ;;
esac

require_root
load_env

: "${ODOO_SERVICE:=odoo.service}"
: "${DB_ROLE:=odoo}"
: "${FILESTORE_ROOT:=/var/lib/odoo/filestore}"
: "${BACKUP_ROOT:=/var/backups/odoo}"
: "${RETENTION_DAYS:=7}"
: "${ODOO_CORE_DIR:=/opt/odoo/odoo}"
: "${PROJECT_DIR:=/opt/odoo/project}"
: "${ODOO_VERSION:=19.0}"
: "${CUSTOM_MODULES:=ardaapp,internship_logbook,sales_app,course_student_management}"

require_value DATABASE_NAME
validate_database_name "$DATABASE_NAME"
require_absolute_safe_path FILESTORE_ROOT
require_absolute_safe_path BACKUP_ROOT
[[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]] || die "RETENTION_DAYS must be a non-negative integer."
[[ -d "$FILESTORE_ROOT/$DATABASE_NAME" ]] || die "Filestore not found: $FILESTORE_ROOT/$DATABASE_NAME"
id "$DB_ROLE" >/dev/null 2>&1 || die "Linux user for peer authentication not found: $DB_ROLE"

for command_name in pg_dump psql tar sha256sum find flock runuser systemctl git; do
    require_command "$command_name"
done

install -d -o root -g root -m 0700 "$BACKUP_ROOT"
exec 9>/run/lock/odoo-backup.lock
flock -n 9 || die "Another Odoo backup is already running."

timestamp="$(date -u +%Y%m%d_%H%M%S)"
set_name="${DATABASE_NAME}_${timestamp}"
staging_dir="$BACKUP_ROOT/.incomplete_${set_name}_$$"
final_dir="$BACKUP_ROOT/$set_name"
dump_name="${DATABASE_NAME}_${timestamp}.dump"
filestore_name="${DATABASE_NAME}_filestore_${timestamp}.tar.gz"
checksum_name="${DATABASE_NAME}_${timestamp}.sha256"
metadata_name="${DATABASE_NAME}_${timestamp}.metadata"
service_was_active=false

cleanup() {
    local rc=$?
    trap - EXIT INT TERM

    if [[ "$service_was_active" == true ]]; then
        log "Starting $ODOO_SERVICE after backup."
        if ! systemctl start "$ODOO_SERVICE"; then
            warn "Backup finished but $ODOO_SERVICE could not be restarted."
            rc=1
        fi
    fi

    if [[ $rc -ne 0 && -d "$staging_dir" ]]; then
        rm -rf -- "$staging_dir"
    fi
    exit "$rc"
}
trap cleanup EXIT INT TERM

install -d -o "$DB_ROLE" -g "$DB_ROLE" -m 0700 "$staging_dir"

if service_is_active "$ODOO_SERVICE"; then
    if [[ "$MODE" == "stop" ]]; then
        log "Stopping $ODOO_SERVICE to keep database and filestore consistent."
        systemctl stop "$ODOO_SERVICE"
        service_was_active=true
    else
        warn "ONLINE backup selected. pg_dump is transaction-consistent, but filestore can change while it is archived."
        warn "Use this mode only with a tested snapshot or maintenance strategy."
    fi
fi

log "Creating PostgreSQL custom-format dump: $dump_name"
runuser -u "$DB_ROLE" -- pg_dump \
    --dbname="$DATABASE_NAME" \
    --format=custom \
    --no-password \
    --file="$staging_dir/$dump_name"

log "Archiving matching filestore: $filestore_name"
tar -C "$FILESTORE_ROOT" -czf "$staging_dir/$filestore_name" -- "$DATABASE_NAME"

postgres_version="$(runuser -u "$DB_ROLE" -- psql --no-password --dbname="$DATABASE_NAME" --tuples-only --no-align --command='SHOW server_version;')"
odoo_commit="$(git_head_or_unknown "$ODOO_CORE_DIR")"
custom_commit="$(git_head_or_unknown "$PROJECT_DIR")"

cat >"$staging_dir/$metadata_name" <<EOF
DATABASE_NAME=$DATABASE_NAME
POSTGRESQL_VERSION=$postgres_version
ODOO_VERSION=$ODOO_VERSION
ODOO_COMMIT=$odoo_commit
CUSTOM_PROJECT_COMMIT=$custom_commit
BACKUP_TIMESTAMP=$timestamp
BACKUP_TIME_UTC=$(date -u --iso-8601=seconds)
BACKUP_TIMEZONE=UTC
CONSISTENCY_MODE=$MODE
CUSTOM_MODULES=$CUSTOM_MODULES
DUMP_FILENAME=$dump_name
FILESTORE_FILENAME=$filestore_name
CHECKSUM_FILENAME=$checksum_name
EOF

(
    cd "$staging_dir"
    sha256sum "$dump_name" "$filestore_name" "$metadata_name" >"$checksum_name"
)

chown -R root:root "$staging_dir"
chmod 0700 "$staging_dir"
chmod 0600 "$staging_dir"/*
mv -- "$staging_dir" "$final_dir"

log "Backup set completed atomically: $final_dir"
log "Removing backup sets older than $RETENTION_DAYS days."
find "$BACKUP_ROOT" \
    -mindepth 1 -maxdepth 1 -type d \
    -name "${DATABASE_NAME}_20*" \
    -mtime "+$RETENTION_DAYS" \
    -print -exec rm -rf -- {} +

warn "A backup kept only on this VPS is not sufficient. Copy encrypted backup sets to tested off-site storage."
