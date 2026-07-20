#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

backup_dir="${BACKUP_DIRECTORY:-${BACKUP_INCOMING_DIR:-}}"
source_db="${SOURCE_DATABASE:-${SOURCE_DATABASE_NAME:-}}"
target_db="${TARGET_DATABASE:-${DATABASE_NAME:-}}"
postgres_role="${POSTGRES_ROLE:-${DB_ROLE:-}}"
filestore_root="${FILESTORE_ROOT:-}"
odoo_os_user="${ODOO_OS_USER:-}"
odoo_os_group="${ODOO_OS_GROUP:-}"
expected_file_count="${EXPECTED_FILE_COUNT:-}"
non_interactive="${NON_INTERACTIVE:-false}"
env_file=""
target_db_created=false
target_filestore_created=false
extract_dir=""
zip_listing=""
target_filestore=""

usage() {
    cat <<'EOF'
Usage:
  sudo migration_restore.sh --backup-dir DIR [options]

Required Windows migration files in DIR:
  odoo_test.dump
  odoo_test_filestore.zip
  checksums.txt
  metadata.txt

Options:
  --backup-dir DIR             Protected incoming backup directory
  --source-db DB               Source database/top-level ZIP directory
  --target-db DB               New target database (must not exist)
  --postgres-role ROLE         Owner of the restored database (default: odoo)
  --filestore-root DIR         Odoo filestore root
  --expected-file-count COUNT  Optional expected physical file count
  --env-file FILE              Load defaults from a protected environment file
  --non-interactive            Require FORCE_MIGRATION_RESTORE=YES and exact
                               MIGRATION_CONFIRMATION instead of a terminal prompt
  -h, --help                   Show this help

The script never drops an existing database or removes an existing filestore.
On failure, any newly created partial target is deliberately left in place for
inspection. Cleanup must be a separate, explicit administrator action.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --backup-dir) backup_dir="${2:-}"; shift 2 ;;
        --source-db) source_db="${2:-}"; shift 2 ;;
        --target-db) target_db="${2:-}"; shift 2 ;;
        --postgres-role) postgres_role="${2:-}"; shift 2 ;;
        --filestore-root) filestore_root="${2:-}"; shift 2 ;;
        --expected-file-count) expected_file_count="${2:-}"; shift 2 ;;
        --env-file) env_file="${2:-}"; shift 2 ;;
        --non-interactive) non_interactive=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done

require_root

if [[ -n "$env_file" ]]; then
    load_env "$env_file"
    backup_dir="${backup_dir:-${BACKUP_DIRECTORY:-${BACKUP_INCOMING_DIR:-}}}"
    source_db="${source_db:-${SOURCE_DATABASE:-${SOURCE_DATABASE_NAME:-odoo_test}}}"
    target_db="${target_db:-${TARGET_DATABASE:-${DATABASE_NAME:-odoo_production}}}"
    postgres_role="${postgres_role:-${POSTGRES_ROLE:-${DB_ROLE:-odoo}}}"
    filestore_root="${filestore_root:-${FILESTORE_ROOT:-/var/lib/odoo/filestore}}"
    expected_file_count="${expected_file_count:-${EXPECTED_FILE_COUNT:-}}"
fi

: "${source_db:=odoo_test}"
: "${target_db:=odoo_production}"
: "${postgres_role:=odoo}"
: "${filestore_root:=/var/lib/odoo/filestore}"
: "${odoo_os_user:=odoo}"
: "${odoo_os_group:=odoo}"
: "${ODOO_SERVICE:=odoo.service}"

# dropdb is verified as an administrator prerequisite but is deliberately never
# invoked here; cleanup of a partial target is a separate manual operation.
for command_name in pg_restore createdb dropdb unzip sha256sum find stat psql \
    runuser awk grep wc tr mktemp install chown chmod id getent mv rm systemctl; do
    require_command "$command_name"
done

validate_database_name "$source_db"
validate_database_name "$target_db"
validate_database_name "$postgres_role"
require_absolute_safe_path filestore_root
[[ -n "$backup_dir" && "$backup_dir" == /* && "$backup_dir" != "/" ]] || \
    die "--backup-dir must be an absolute path other than /."
secure_directory_check "$backup_dir" root root

if [[ -n "$expected_file_count" && ! "$expected_file_count" =~ ^[0-9]+$ ]]; then
    die "Expected file count must be a non-negative integer."
fi

if [[ "$source_db" == "$target_db" ]]; then
    warn "SOURCE_DATABASE and TARGET_DATABASE are identical: $target_db"
    [[ "${ALLOW_SAME_DATABASE_NAME:-NO}" == "YES" ]] || \
        die "Set ALLOW_SAME_DATABASE_NAME=YES only after verifying this unusual migration plan."
fi

dump_name="${source_db}.dump"
filestore_name="${source_db}_filestore.zip"
checksum_name="checksums.txt"
metadata_name="metadata.txt"
dump_file="$backup_dir/$dump_name"
filestore_file="$backup_dir/$filestore_name"
checksum_file="$backup_dir/$checksum_name"
metadata_file="$backup_dir/$metadata_name"

for required_file in "$dump_file" "$filestore_file" "$checksum_file" "$metadata_file"; do
    require_file "$required_file"
    file_owner="$(stat -c '%U' "$required_file")"
    file_mode="$(stat -c '%a' "$required_file")"
    [[ "$file_owner" == "root" ]] || die "$required_file must be owned by root."
    [[ "$file_mode" == "600" ]] || \
        die "$required_file must have mode 0600 (current mode: $file_mode)."
done

metadata_value() {
    local key="$1"
    awk -F: -v wanted="$key" '$1 == wanted {sub(/^[^:]*:[[:space:]]*/, ""); sub(/\r$/, ""); print; exit}' "$metadata_file"
}

metadata_source_db="$(metadata_value 'Database Name')"
metadata_dump_name="$(metadata_value 'Database Dump Filename')"
metadata_filestore_name="$(metadata_value 'Filestore Backup Filename')"
metadata_file_count="$(metadata_value 'Filestore File Count')"
[[ "$metadata_source_db" == "$source_db" ]] || \
    die "metadata.txt database name does not match SOURCE_DATABASE."
[[ "$metadata_dump_name" == "$dump_name" ]] || \
    die "metadata.txt dump filename does not match the expected Windows backup filename."
[[ "$metadata_filestore_name" == "$filestore_name" ]] || \
    die "metadata.txt filestore filename does not match the expected Windows backup filename."
if [[ -z "$expected_file_count" && "$metadata_file_count" =~ ^[0-9]+$ ]]; then
    expected_file_count="$metadata_file_count"
fi

cleanup_temp() {
    local rc=$?
    trap - EXIT
    if [[ $rc -ne 0 ]]; then
        warn "Migration restore failed. Backup files were not modified."
        [[ "$target_db_created" == true ]] && \
            warn "A partial database may remain and must be inspected or explicitly removed: $target_db"
        [[ "$target_filestore_created" == true || ( -n "$target_filestore" && -e "$target_filestore" ) ]] && \
            warn "A partial filestore may remain and must be inspected or explicitly removed: $target_filestore"
        warn "No automatic drop, deletion or destructive cleanup was performed."
    fi
    [[ -n "$zip_listing" && -f "$zip_listing" ]] && rm -f -- "$zip_listing"
    [[ -n "$extract_dir" && -d "$extract_dir" ]] && rm -rf -- "$extract_dir"
    exit "$rc"
}
trap cleanup_temp EXIT

checksum_for() {
    local wanted="$1"
    awk -v wanted="$wanted" '
        {sub(/\r$/, "", $NF)}
        toupper($1) == "SHA256" && length($2) == 64 && $2 ~ /^[0-9A-Fa-f]+$/ && $3 == wanted {print tolower($2); found++}
        length($1) == 64 && $1 ~ /^[0-9A-Fa-f]+$/ && $2 == wanted {print tolower($1); found++}
        END {if (found != 1) exit 1}
    ' "$checksum_file"
}

log "Verifying the two Windows migration SHA-256 checksums."
for backup_name in "$dump_name" "$filestore_name"; do
    expected_checksum="$(checksum_for "$backup_name")" || \
        die "checksums.txt must contain exactly one valid SHA-256 entry for $backup_name."
    actual_checksum="$(sha256sum "$backup_dir/$backup_name" | awk '{print tolower($1)}')"
    [[ "$actual_checksum" == "$expected_checksum" ]] || die "SHA-256 mismatch: $backup_name"
    log "SHA-256 verified: $backup_name"
done

log "Checking PostgreSQL custom-format dump catalog."
pg_restore --list "$dump_file" >/dev/null

log "Checking ZIP integrity and path layout."
unzip -t "$filestore_file" >/dev/null
zip_listing="$(mktemp "${TMPDIR:-/var/tmp}/odoo-migration-zip-list.XXXXXX")"
unzip -Z1 "$filestore_file" >"$zip_listing"
if grep -Eq '(^/|^[A-Za-z]:|(^|/)\.\.(/|$)|\\)' "$zip_listing"; then
    die "Unsafe absolute, parent, drive-letter or backslash path found in filestore ZIP."
fi
if grep -Ev "^${source_db}/" "$zip_listing" | grep -q .; then
    die "ZIP must contain only the $source_db/ top-level directory."
fi
grep -q "^${source_db}/" "$zip_listing" || \
    die "ZIP does not contain the expected top-level directory: $source_db/"
rm -f -- "$zip_listing"
zip_listing=""

db_exists="$(runuser -u postgres -- psql --dbname=postgres --tuples-only --no-align \
    --command="SELECT 1 FROM pg_database WHERE datname = '$target_db';")"
[[ -z "$db_exists" ]] || die "Target database already exists; it will not be dropped: $target_db"

target_filestore="$filestore_root/$target_db"
[[ ! -L "$filestore_root" ]] || die "Filestore root must not be a symbolic link: $filestore_root"
[[ ! -e "$target_filestore" ]] || \
    die "Target filestore already exists; it will not be removed: $target_filestore"

role_exists="$(runuser -u postgres -- psql --dbname=postgres --tuples-only --no-align \
    --command="SELECT 1 FROM pg_roles WHERE rolname = '$postgres_role';")"
[[ -n "$role_exists" ]] || die "PostgreSQL role does not exist: $postgres_role"
id "$odoo_os_user" >/dev/null 2>&1 || die "Odoo OS user does not exist: $odoo_os_user"
getent group "$odoo_os_group" >/dev/null 2>&1 || die "Odoo OS group does not exist: $odoo_os_group"
if systemctl is-active --quiet "$ODOO_SERVICE"; then
    die "$ODOO_SERVICE is active. Stop the verified Odoo 19 production service before migration restore."
fi

confirmation="MIGRATE $source_db TO $target_db"
warn "This creates a new production target database and filestore: $target_db"
if [[ "$non_interactive" == true || "$non_interactive" == "1" ]]; then
    [[ "${FORCE_MIGRATION_RESTORE:-NO}" == "YES" ]] || \
        die "Non-interactive restore requires FORCE_MIGRATION_RESTORE=YES."
    [[ "${MIGRATION_CONFIRMATION:-}" == "$confirmation" ]] || \
        die "MIGRATION_CONFIRMATION must equal exactly: $confirmation"
else
    confirm_exact "$confirmation" \
        "PRODUCTION MIGRATION: source backup is $source_db; new target is $target_db. Existing targets are never replaced."
fi

log "Creating UTF8 database from template0, owner $postgres_role: $target_db"
runuser -u postgres -- createdb \
    --owner="$postgres_role" \
    --encoding=UTF8 \
    --template=template0 \
    "$target_db"
target_db_created=true

log "Restoring PostgreSQL dump without source ownership or ACL entries."
runuser -u postgres -- pg_restore \
    --exit-on-error \
    --no-owner \
    --no-privileges \
    --role="$postgres_role" \
    --dbname="$target_db" \
    "$dump_file"

runuser -u postgres -- psql --dbname="$target_db" --no-align --tuples-only \
    --command='SELECT current_database();' >/dev/null
runuser -u postgres -- psql --dbname="$target_db" --set=ON_ERROR_STOP=1 \
    --command='ANALYZE;'

log "Base module version:"
runuser -u postgres -- psql --dbname="$target_db" --no-align --tuples-only \
    --command="SELECT COALESCE(latest_version, 'unknown') FROM ir_module_module WHERE name = 'base';"
log "Custom module states:"
runuser -u postgres -- psql --dbname="$target_db" --no-align --tuples-only \
    --command="SELECT name || '=' || state FROM ir_module_module WHERE name IN ('ardaapp','internship_logbook','sales_app','course_student_management') ORDER BY name;"
installed_custom_count="$(runuser -u postgres -- psql --dbname="$target_db" --no-align --tuples-only \
    --command="SELECT count(*) FROM ir_module_module WHERE name IN ('ardaapp','internship_logbook','sales_app','course_student_management') AND state = 'installed';")"
[[ "$installed_custom_count" == "4" ]] || \
    die "Expected all four custom modules to be installed; installed count is $installed_custom_count."

extract_dir="$(mktemp -d "${TMPDIR:-/var/tmp}/odoo-migration-extract.XXXXXX")"
unzip -q "$filestore_file" -d "$extract_dir"
source_filestore="$extract_dir/$source_db"
[[ -d "$source_filestore" ]] || die "Extracted ZIP is missing $source_db/."
[[ -z "$(find "$source_filestore" -type l -print -quit)" ]] || \
    die "Extracted filestore must not contain symbolic links."
[[ -z "$(find "$source_filestore" ! -type f ! -type d -print -quit)" ]] || \
    die "Extracted filestore contains an unsupported filesystem object."

source_file_count="$(find "$source_filestore" -type f -print | wc -l | tr -d '[:space:]')"
[[ "$source_file_count" -gt 0 ]] || die "Extracted filestore contains no physical files."
if [[ -n "$expected_file_count" && "$source_file_count" -ne "$expected_file_count" ]]; then
    die "Filestore file count differs from expected value: expected=$expected_file_count actual=$source_file_count"
fi

install -d -o "$odoo_os_user" -g "$odoo_os_group" -m 0750 "$filestore_root"
mv -- "$source_filestore" "$target_filestore"
target_filestore_created=true
chown -R "$odoo_os_user:$odoo_os_group" "$target_filestore"
find "$target_filestore" -type d -exec chmod 0750 {} +
find "$target_filestore" -type f -exec chmod 0640 {} +

target_file_count="$(find "$target_filestore" -type f -print | wc -l | tr -d '[:space:]')"
[[ "$target_file_count" -eq "$source_file_count" ]] || \
    die "Filestore copy count mismatch: source=$source_file_count target=$target_file_count"

log "Windows migration restore completed successfully."
log "Database: $target_db"
log "Filestore: $target_filestore"
log "Physical filestore files: $target_file_count"
log "Odoo was not started. Run the documented registry test before enabling the production service."
