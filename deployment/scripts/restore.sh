#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

backup_dir=""
target_db=""
production=false
replace_existing=false

usage() {
    cat <<'EOF'
Usage:
  sudo restore.sh --backup-dir DIR --target-db DB
  sudo restore.sh --backup-dir DIR --target-db DB --production --replace-existing

The safe default restores only into a new/staging database. Restoring over an
existing or production database requires both explicit flags and an exact
interactive confirmation. The previous database and filestore are renamed,
not silently deleted, to support rollback.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --backup-dir) backup_dir="${2:-}"; shift 2 ;;
        --target-db) target_db="${2:-}"; shift 2 ;;
        --production) production=true; shift ;;
        --replace-existing) replace_existing=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done

require_root
load_env

: "${DB_ROLE:=odoo}"
: "${FILESTORE_ROOT:=/var/lib/odoo/filestore}"
: "${ODOO_SERVICE:=odoo.service}"
: "${PRODUCTION_DATABASE:=${DATABASE_NAME:-}}"

[[ -n "$backup_dir" && -d "$backup_dir" ]] || die "A valid --backup-dir is required."
[[ -n "$target_db" ]] || die "--target-db is required."
validate_database_name "$target_db"
require_absolute_safe_path FILESTORE_ROOT

for command_name in psql createdb pg_restore tar sha256sum runuser systemctl awk find grep; do
    require_command "$command_name"
done

mapfile -t metadata_files < <(find "$backup_dir" -maxdepth 1 -type f -name '*.metadata' -print)
[[ ${#metadata_files[@]} -eq 1 ]] || die "Backup directory must contain exactly one .metadata file."
metadata_file="${metadata_files[0]}"

metadata_value() {
    local key="$1"
    awk -F= -v wanted="$key" '$1 == wanted {sub(/^[^=]*=/, ""); print; exit}' "$metadata_file"
}

source_db="$(metadata_value DATABASE_NAME)"
timestamp="$(metadata_value BACKUP_TIMESTAMP)"
dump_name="$(metadata_value DUMP_FILENAME)"
filestore_name="$(metadata_value FILESTORE_FILENAME)"
checksum_name="$(metadata_value CHECKSUM_FILENAME)"

validate_database_name "$source_db"
[[ "$timestamp" =~ ^[0-9]{8}_[0-9]{6}$ ]] || die "Invalid or missing backup timestamp in metadata."
[[ "$dump_name" == "${source_db}_${timestamp}.dump" ]] || die "Dump filename does not match metadata timestamp."
[[ "$filestore_name" == "${source_db}_filestore_${timestamp}.tar.gz" ]] || die "Filestore filename does not match metadata timestamp."
[[ "$checksum_name" == "${source_db}_${timestamp}.sha256" ]] || die "Checksum filename does not match metadata timestamp."

for required_file in "$dump_name" "$filestore_name" "$checksum_name"; do
    [[ -f "$backup_dir/$required_file" ]] || die "Incomplete backup set; missing $required_file"
done

log "Verifying SHA-256 checksums."
(
    cd "$backup_dir"
    sha256sum --check "$checksum_name"
)

if tar -tzf "$backup_dir/$filestore_name" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
    die "Unsafe path found inside filestore archive."
fi

db_exists="$(runuser -u postgres -- psql --dbname=postgres --tuples-only --no-align \
    --command="SELECT 1 FROM pg_database WHERE datname = '$target_db';")"

if [[ "$target_db" == "$PRODUCTION_DATABASE" ]]; then
    production=true
fi

if [[ "$production" == true ]]; then
    [[ "$replace_existing" == true ]] || die "Production restore requires --replace-existing."
    confirm_exact "RESTORE $target_db" \
        "DESTRUCTIVE CUTOVER: target database is $target_db. The existing database and filestore will be renamed for rollback."
elif [[ -n "$db_exists" ]]; then
    die "Target database already exists. Safe default is a new staging database."
fi

if [[ -n "$db_exists" && "$replace_existing" != true ]]; then
    die "Existing target requires --production --replace-existing and explicit confirmation."
fi

service_was_active=false
if [[ "$production" == true ]] && service_is_active "$ODOO_SERVICE"; then
    log "Stopping $ODOO_SERVICE for production restore."
    systemctl stop "$ODOO_SERVICE"
    service_was_active=true
fi

rollback_suffix="pre_restore_${timestamp}"
previous_db="${target_db:0:30}_${rollback_suffix}"
previous_filestore="$FILESTORE_ROOT/${target_db}.${rollback_suffix}"

if [[ -n "$db_exists" ]]; then
    log "Preserving current database as $previous_db"
    runuser -u postgres -- psql --dbname=postgres --command="SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$target_db' AND pid <> pg_backend_pid();"
    runuser -u postgres -- psql --dbname=postgres --command="ALTER DATABASE \"$target_db\" RENAME TO \"$previous_db\";"
fi

log "Creating empty target database owned by $DB_ROLE: $target_db"
runuser -u postgres -- createdb --owner="$DB_ROLE" --template=template0 "$target_db"

log "Restoring PostgreSQL dump into $target_db"
if ! runuser -u postgres -- pg_restore \
    --exit-on-error \
    --no-owner \
    --role="$DB_ROLE" \
    --dbname="$target_db" \
    "$backup_dir/$dump_name"; then
    warn "Database restore failed. $target_db is incomplete and Odoo remains stopped."
    [[ -n "$db_exists" ]] && warn "Rollback database is preserved as $previous_db."
    exit 1
fi

extract_dir="$(mktemp -d "$FILESTORE_ROOT/.restore_${target_db}_XXXXXX")"
trap 'rm -rf -- "$extract_dir"' EXIT
tar -xzf "$backup_dir/$filestore_name" -C "$extract_dir"
[[ -d "$extract_dir/$source_db" ]] || die "Filestore archive does not contain expected top-level directory: $source_db"

target_filestore="$FILESTORE_ROOT/$target_db"
if [[ -e "$target_filestore" ]]; then
    [[ "$production" == true && "$replace_existing" == true ]] || die "Target filestore already exists: $target_filestore"
    log "Preserving current filestore as $previous_filestore"
    mv -- "$target_filestore" "$previous_filestore"
fi

mv -- "$extract_dir/$source_db" "$target_filestore"
chown -R "$DB_ROLE:$DB_ROLE" "$target_filestore"
find "$target_filestore" -type d -exec chmod 0750 {} +
find "$target_filestore" -type f -exec chmod 0640 {} +
runuser -u postgres -- psql --dbname="$target_db" --command='ANALYZE;'

trap - EXIT
rm -rf -- "$extract_dir"

log "Restore completed successfully into $target_db"
if [[ "$production" == true ]]; then
    log "Previous database: ${previous_db:-none}"
    log "Previous filestore: ${previous_filestore:-none}"
    if [[ "$service_was_active" == true ]]; then
        systemctl start "$ODOO_SERVICE"
        log "$ODOO_SERVICE restarted. Verify login, attachments, mail and PDF before removing rollback copies."
    fi
else
    log "Staging restore does not start the production Odoo service. Test it with a separate config/service."
fi
