#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

case "${1:-}" in
    "") ;;
    -h|--help)
        cat <<'EOF'
Usage: sudo offsite_backup.sh

Verify completed local Odoo backup sets and upload them to the configured
off-site rclone destination. This script never deletes or modifies local or
remote backup files and never uses rclone sync.
EOF
        exit 0
        ;;
    *) die "Unknown option: $1" ;;
esac

require_root
umask 0077
load_env

: "${BACKUP_ROOT:=/var/backups/odoo}"
: "${RCLONE_CONFIG:=/etc/rclone/odoo-rclone.conf}"
: "${OFFSITE_REMOTE:=gdrive:Odoo-Production-Backups}"
: "${OFFSITE_LOCK_FILE:=/run/lock/odoo-offsite-backup.lock}"

require_value DATABASE_NAME
validate_database_name "$DATABASE_NAME"
require_absolute_safe_path BACKUP_ROOT
require_absolute_safe_path RCLONE_CONFIG
require_absolute_safe_path OFFSITE_LOCK_FILE

[[ "$OFFSITE_REMOTE" =~ ^[a-zA-Z0-9._-]+:[^[:space:]]+$ ]] || \
    die "OFFSITE_REMOTE must be an rclone remote path without whitespace."
remote_root="${OFFSITE_REMOTE%/}"

for command_name in rclone flock find sha256sum stat awk wc basename sort dirname chmod; do
    require_command "$command_name"
done

secure_directory_check "$BACKUP_ROOT" root root
require_file "$RCLONE_CONFIG"
[[ "$(stat -c '%U:%G %a' "$RCLONE_CONFIG")" == "root:root 600" ]] || \
    die "$RCLONE_CONFIG must be owned by root:root with mode 0600."

lock_parent="$(dirname -- "$OFFSITE_LOCK_FILE")"
[[ -d "$lock_parent" && ! -L "$lock_parent" ]] || \
    die "Off-site lock directory is missing or unsafe: $lock_parent"
[[ ! -L "$OFFSITE_LOCK_FILE" ]] || die "Off-site lock file must not be a symbolic link: $OFFSITE_LOCK_FILE"
exec 8>"$OFFSITE_LOCK_FILE"
chmod 0600 "$OFFSITE_LOCK_FILE"
flock -n 8 || die "Another off-site backup upload is already running."

validate_manifest() {
    local manifest_file="$1"
    local expected_dump="$2"
    local expected_filestore="$3"
    local expected_metadata="$4"

    awk \
        -v dump="$expected_dump" \
        -v filestore="$expected_filestore" \
        -v metadata="$expected_metadata" '
        {
            sub(/\r$/, "")
            if (NF != 2) exit 1
            hash = $1
            filename = $2
            sub(/^\*/, "", filename)
            if (length(hash) != 64 || hash !~ /^[0-9A-Fa-f]+$/) exit 1
            if (filename == dump) dump_seen++
            else if (filename == filestore) filestore_seen++
            else if (filename == metadata) metadata_seen++
            else exit 1
            line_count++
        }
        END {
            if (line_count != 3 || dump_seen != 1 || filestore_seen != 1 || metadata_seen != 1) exit 1
        }
    ' "$manifest_file"
}

validate_backup_set() {
    local set_dir="$1"
    local set_name="$2"
    local timestamp="${set_name#${DATABASE_NAME}_}"
    local dump_name="${set_name}.dump"
    local filestore_name="${DATABASE_NAME}_filestore_${timestamp}.tar.gz"
    local metadata_name="${set_name}.metadata"
    local checksum_name="${set_name}.sha256"
    local expected_file entry_count

    secure_directory_check "$set_dir" root root

    entry_count="$(find "$set_dir" -mindepth 1 -maxdepth 1 -print | wc -l)"
    [[ "$entry_count" -eq 4 ]] || \
        die "Backup set must contain exactly four top-level entries: $set_name (found: $entry_count)"

    for expected_file in "$dump_name" "$filestore_name" "$metadata_name" "$checksum_name"; do
        require_file "$set_dir/$expected_file"
        [[ "$(stat -c '%U:%G %a' "$set_dir/$expected_file")" == "root:root 600" ]] || \
            die "Backup file must be root:root 0600: $set_dir/$expected_file"
    done

    validate_manifest \
        "$set_dir/$checksum_name" \
        "$dump_name" \
        "$filestore_name" \
        "$metadata_name" || die "Unsafe or incomplete SHA-256 manifest: $set_dir/$checksum_name"

    log "Verifying local SHA-256 manifest: $set_name"
    (
        cd "$set_dir"
        sha256sum --check --strict "$checksum_name"
    )
}

upload_backup_set() {
    local set_dir="$1"
    local set_name="$2"
    local timestamp="${set_name#${DATABASE_NAME}_}"
    local remote_set="$remote_root/$set_name"
    local expected_files=(
        "${set_name}.dump"
        "${DATABASE_NAME}_filestore_${timestamp}.tar.gz"
        "${set_name}.metadata"
        "${set_name}.sha256"
    )
    local expected_file

    if rclone --config="$RCLONE_CONFIG" check \
        "$set_dir" "$remote_set" \
        --one-way --checkers=4 --log-level ERROR >/dev/null 2>&1; then
        log "Remote backup set is already complete; skipping upload: $set_name"
        return 0
    fi

    log "Uploading verified backup set with immutable copy semantics: $set_name"
    for expected_file in "${expected_files[@]}"; do
        if ! rclone --config="$RCLONE_CONFIG" copyto \
            "$set_dir/$expected_file" \
            "$remote_set/$expected_file" \
            --immutable --log-level NOTICE; then
            die "Off-site upload failed: $set_name/$expected_file"
        fi
    done

    log "Verifying the completed remote backup set: $set_name"
    if ! rclone --config="$RCLONE_CONFIG" check \
        "$set_dir" "$remote_set" \
        --one-way --checkers=4 --log-level NOTICE; then
        die "Remote verification failed after upload: $set_name"
    fi

    log "Off-site backup verified successfully: $remote_set"
}

found_completed_set=false
uploaded_or_verified=0
while IFS= read -r -d '' set_dir; do
    set_name="$(basename -- "$set_dir")"
    if [[ ! "$set_name" =~ ^${DATABASE_NAME}_[0-9]{8}_[0-9]{6}$ ]]; then
        continue
    fi

    found_completed_set=true
    log "Inspecting completed local backup set: $set_name"
    validate_backup_set "$set_dir" "$set_name"
    upload_backup_set "$set_dir" "$set_name"
    ((uploaded_or_verified += 1))
done < <(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -print0 | sort -z)

if [[ "$found_completed_set" != true ]]; then
    warn "No completed backup directory matched ${DATABASE_NAME}_YYYYMMDD_HHMMSS under $BACKUP_ROOT."
    exit 0
fi

log "Off-site backup run completed; verified sets: $uploaded_or_verified"
log "No local or remote backup files were deleted."
