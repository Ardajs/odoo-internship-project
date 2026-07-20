#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

skip_backup=false
for arg in "$@"; do
    case "$arg" in
        --skip-backup) skip_backup=true ;;
        -h|--help)
            cat <<'EOF'
Usage: sudo update.sh [--skip-backup]

Updates only the custom repository by fast-forward, upgrades the four custom
modules, restarts Odoo and performs local health checks. Odoo core is never
fetched or changed. Backup is mandatory unless explicitly skipped with an
interactive confirmation.
EOF
            exit 0
            ;;
        *) die "Unknown option: $arg" ;;
    esac
done

require_root
load_env

: "${ODOO_CORE_DIR:=/opt/odoo/odoo}"
: "${PROJECT_DIR:=/opt/odoo/project}"
: "${VENV_DIR:=/opt/odoo/venv}"
: "${ODOO_CONFIG:=/etc/odoo/odoo.conf}"
: "${ODOO_SERVICE:=odoo.service}"
: "${CUSTOM_BRANCH:=main}"
: "${CUSTOM_MODULES:=ardaapp,internship_logbook,sales_app,course_student_management}"

require_value DATABASE_NAME
validate_database_name "$DATABASE_NAME"
[[ -d "$PROJECT_DIR/.git" ]] || die "Custom project Git checkout not found: $PROJECT_DIR"
[[ -d "$ODOO_CORE_DIR/.git" ]] || die "Pinned Odoo core checkout not found: $ODOO_CORE_DIR"
[[ -x "$VENV_DIR/bin/python3" ]] || die "Python virtualenv not found: $VENV_DIR"
[[ -r "$ODOO_CONFIG" ]] || die "Odoo config not found: $ODOO_CONFIG"
[[ "$(git -C "$PROJECT_DIR" symbolic-ref --quiet --short HEAD)" == "$CUSTOM_BRANCH" ]] || \
    die "Custom repository must be on branch $CUSTOM_BRANCH before update."

for command_name in git systemctl curl runuser; do
    require_command "$command_name"
done

if [[ -n "$(git -C "$PROJECT_DIR" status --porcelain)" ]]; then
    die "Custom repository has local changes. Commit/stash them before production update."
fi

core_before="$(git -C "$ODOO_CORE_DIR" rev-parse HEAD)"
old_custom_commit="$(git -C "$PROJECT_DIR" rev-parse HEAD)"

if [[ "$skip_backup" == true ]]; then
    confirm_exact "SKIP BACKUP" "Skipping the pre-update backup increases rollback risk."
else
    "$SCRIPT_DIR/backup.sh" --consistent
fi

log "Fetching custom repository only. Odoo core remains pinned at $core_before"
git -C "$PROJECT_DIR" fetch --prune origin "$CUSTOM_BRANCH"
git -C "$PROJECT_DIR" merge-base --is-ancestor HEAD "origin/$CUSTOM_BRANCH" || \
    die "Custom branch diverged or would require a non-fast-forward update."
git -C "$PROJECT_DIR" merge --ff-only "origin/$CUSTOM_BRANCH"
new_custom_commit="$(git -C "$PROJECT_DIR" rev-parse HEAD)"

[[ "$(git -C "$ODOO_CORE_DIR" rev-parse HEAD)" == "$core_before" ]] || \
    die "Odoo core changed unexpectedly; aborting."

update_in_progress=true
update_cleanup() {
    local rc=$?
    trap - EXIT INT TERM
    if [[ $rc -ne 0 && "$update_in_progress" == true ]]; then
        systemctl stop "$ODOO_SERVICE" >/dev/null 2>&1 || true
        warn "Update failed. Odoo is intentionally left stopped to avoid serving mismatched code/database state."
        warn "Previous custom commit: $old_custom_commit"
        warn "Current custom commit:  $new_custom_commit"
        warn "Use the verified pre-update backup and documented rollback procedure."
    fi
    exit "$rc"
}
trap update_cleanup EXIT
trap 'exit 130' INT TERM

systemctl stop "$ODOO_SERVICE"
log "Upgrading custom modules: $CUSTOM_MODULES"
runuser -u odoo -- "$VENV_DIR/bin/python3" "$ODOO_CORE_DIR/odoo-bin" \
    --config="$ODOO_CONFIG" \
    --database="$DATABASE_NAME" \
    --update="$CUSTOM_MODULES" \
    --stop-after-init \
    --no-http

systemctl start "$ODOO_SERVICE"

for attempt in {1..30}; do
    if curl --fail --silent --show-error http://127.0.0.1:8069/web/login >/dev/null; then
        break
    fi
    [[ "$attempt" -lt 30 ]] || die "Odoo HTTP health check failed after restart."
    sleep 2
done

curl --fail --silent --show-error http://127.0.0.1:8072/websocket/health >/dev/null || \
    die "Odoo websocket health check failed on 127.0.0.1:8072."
systemctl is-active --quiet "$ODOO_SERVICE" || die "$ODOO_SERVICE is not active."

update_in_progress=false
trap - EXIT INT TERM
log "Custom update completed: $old_custom_commit -> $new_custom_commit"
log "Pinned Odoo core remains unchanged: $core_before"
