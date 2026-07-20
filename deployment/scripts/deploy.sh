#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

apply=false
skip_db_check=false

for arg in "$@"; do
    case "$arg" in
        --apply) apply=true ;;
        --skip-db-check) skip_db_check=true ;;
        -h|--help)
            cat <<'EOF'
Usage: sudo deploy.sh --apply [--skip-db-check]

The --apply flag is mandatory because this script creates the system user,
directories, pinned Odoo checkout, custom checkout and Python virtualenv.
It does not install APT packages, restore a database, install Nginx or start
the Odoo service. Use --skip-db-check only before the first database restore.
EOF
            exit 0
            ;;
        *) die "Unknown option: $arg" ;;
    esac
done

[[ "$apply" == true ]] || die "No changes made. Review the script, then run explicitly with --apply."
require_root
load_env

: "${ODOO_CORE_REPO:=https://github.com/odoo/odoo.git}"
: "${ODOO_CORE_DIR:=/opt/odoo/odoo}"
: "${PROJECT_DIR:=/opt/odoo/project}"
: "${VENV_DIR:=/opt/odoo/venv}"
: "${ODOO_CONFIG:=/etc/odoo/odoo.conf}"
: "${FILESTORE_ROOT:=/var/lib/odoo/filestore}"
: "${LOG_DIR:=/var/log/odoo}"
: "${BACKUP_ROOT:=/var/backups/odoo}"
: "${CUSTOM_BRANCH:=main}"
: "${DB_ROLE:=odoo}"

for variable in ODOO_VERSION ODOO_COMMIT GITHUB_REPO_URL DATABASE_NAME; do
    require_value "$variable"
done
[[ "$ODOO_VERSION" == "19.0" ]] || die "This deployment package is validated for Odoo branch 19.0."
[[ "$ODOO_COMMIT" =~ ^[0-9a-fA-F]{40}$ ]] || die "ODOO_COMMIT must be a full 40-character tested commit SHA."
validate_database_name "$DATABASE_NAME"
for variable in ODOO_CORE_DIR PROJECT_DIR VENV_DIR FILESTORE_ROOT LOG_DIR BACKUP_ROOT; do
    require_absolute_safe_path "$variable"
done

for command_name in git python3.12 sha256sum psql runuser; do
    require_command "$command_name"
done

if ! id odoo >/dev/null 2>&1; then
    log "Creating locked system user odoo."
    useradd --system --home-dir /var/lib/odoo --create-home --shell /usr/sbin/nologin --user-group odoo
fi

install -d -o root -g odoo -m 0750 /opt/odoo /etc/odoo
install -d -o odoo -g odoo -m 0750 /var/lib/odoo "$FILESTORE_ROOT" "$FILESTORE_ROOT/$DATABASE_NAME" "$LOG_DIR"
install -d -o root -g root -m 0700 "$BACKUP_ROOT"

if [[ ! -d "$ODOO_CORE_DIR/.git" ]]; then
    [[ ! -e "$ODOO_CORE_DIR" || -z "$(find "$ODOO_CORE_DIR" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]] || \
        die "$ODOO_CORE_DIR exists and is not an empty Git checkout."
    log "Cloning Odoo branch $ODOO_VERSION without selecting an untested latest commit."
    git clone --branch "$ODOO_VERSION" --single-branch "$ODOO_CORE_REPO" "$ODOO_CORE_DIR"
fi

log "Fetching Odoo branch metadata without updating the working checkout."
git -C "$ODOO_CORE_DIR" fetch --no-tags origin \
    "+refs/heads/$ODOO_VERSION:refs/remotes/origin/$ODOO_VERSION"
git -C "$ODOO_CORE_DIR" cat-file -e "${ODOO_COMMIT}^{commit}" || die "ODOO_COMMIT is not a valid fetched commit."
git -C "$ODOO_CORE_DIR" merge-base --is-ancestor "$ODOO_COMMIT" "origin/$ODOO_VERSION" || \
    die "ODOO_COMMIT is not part of origin/$ODOO_VERSION."
log "Checking out explicitly configured Odoo commit: $ODOO_COMMIT"
git -C "$ODOO_CORE_DIR" checkout --detach "$ODOO_COMMIT"
[[ "$(git -C "$ODOO_CORE_DIR" rev-parse HEAD)" == "$(git -C "$ODOO_CORE_DIR" rev-parse "$ODOO_COMMIT")" ]] || \
    die "Pinned Odoo commit verification failed."

if [[ ! -d "$PROJECT_DIR/.git" ]]; then
    [[ ! -e "$PROJECT_DIR" || -z "$(find "$PROJECT_DIR" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]] || \
        die "$PROJECT_DIR exists and is not an empty Git checkout."
    log "Cloning custom project branch $CUSTOM_BRANCH."
    git clone --branch "$CUSTOM_BRANCH" --single-branch "$GITHUB_REPO_URL" "$PROJECT_DIR"
fi
[[ "$(git -C "$PROJECT_DIR" symbolic-ref --quiet --short HEAD)" == "$CUSTOM_BRANCH" ]] || \
    die "$PROJECT_DIR must be on the configured custom branch: $CUSTOM_BRANCH"

for addon in \
    "$PROJECT_DIR/dev_addons/ardaapp/__manifest__.py" \
    "$PROJECT_DIR/dev_addonsI/internship_logbook/__manifest__.py" \
    "$PROJECT_DIR/dev_addonsI/sales_app/__manifest__.py" \
    "$PROJECT_DIR/custom_addons/course_student_management/__manifest__.py"; do
    [[ -r "$addon" ]] || die "Required custom addon is missing: $addon"
done

if [[ ! -x "$VENV_DIR/bin/python3" ]]; then
    log "Creating a new Linux Python 3.12 virtual environment at $VENV_DIR"
    python3.12 -m venv "$VENV_DIR"
fi

requirements="$ODOO_CORE_DIR/requirements.txt"
[[ -r "$requirements" ]] || die "Odoo requirements file not found: $requirements"
requirements_hash="$(sha256sum "$requirements" | awk '{print $1}')"
stamp="$VENV_DIR/.odoo-requirements.sha256"

if [[ ! -f "$stamp" || "$(cat "$stamp")" != "$requirements_hash" ]]; then
    log "Installing pinned Odoo Python requirements into the Linux virtualenv."
    "$VENV_DIR/bin/pip" install setuptools wheel
    "$VENV_DIR/bin/pip" install --requirement "$requirements"
    printf '%s\n' "$requirements_hash" >"$stamp"
fi

[[ -f "$ODOO_CONFIG" ]] || die "Production config is missing: $ODOO_CONFIG"
if grep -Eq 'DATABASE_NAME|ODOO_MASTER_PASSWORD|CHANGE_ME' "$ODOO_CONFIG"; then
    die "$ODOO_CONFIG still contains a placeholder."
fi
chown root:odoo "$ODOO_CONFIG"
chmod 0640 "$ODOO_CONFIG"

if [[ "$skip_db_check" != true ]]; then
    log "Checking PostgreSQL Unix-socket access as Linux user odoo."
    runuser -u odoo -- psql --no-password --dbname="$DATABASE_NAME" --tuples-only --no-align --command='SELECT 1;' | grep -qx '1' || \
        die "PostgreSQL connection failed for $DATABASE_NAME."
else
    warn "Database check skipped explicitly. Do not start Odoo until the database and matching filestore are restored."
fi

log "Deployment prerequisites are ready."
log "Odoo core commit: $(git -C "$ODOO_CORE_DIR" rev-parse HEAD)"
log "Custom project commit: $(git -C "$PROJECT_DIR" rev-parse HEAD)"
warn "This script did not install/start systemd, Nginx, Certbot or UFW. Follow DEPLOYMENT_GUIDE.md."
