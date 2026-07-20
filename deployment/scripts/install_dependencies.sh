#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

apply=false
with_postgresql=false

for arg in "$@"; do
    case "$arg" in
        --apply) apply=true ;;
        --with-postgresql) with_postgresql=true ;;
        -h|--help)
            cat <<'EOF'
Usage: sudo install_dependencies.sh [--apply] [--with-postgresql]

Without --apply the script only prints the plan. It never adds third-party APT
repositories or downloads wkhtmltopdf binaries automatically.

--with-postgresql installs postgresql-17 and postgresql-client-17 only when
those packages are already available from a repository configured by the
administrator according to the official PostgreSQL instructions.
EOF
            exit 0
            ;;
        *) die "Unknown option: $arg" ;;
    esac
done

[[ -r /etc/os-release ]] || die "Cannot identify the operating system."
# shellcheck disable=SC1091
source /etc/os-release
[[ "${ID:-}" == "ubuntu" && "${VERSION_ID:-}" == "24.04" ]] || \
    die "This script is intentionally limited to Ubuntu 24.04; detected ${ID:-unknown} ${VERSION_ID:-unknown}."

base_packages=(
    ca-certificates curl git build-essential
    python3.12 python3.12-venv python3.12-dev python3-pip
    libldap2-dev libpq-dev libsasl2-dev
    libxml2-dev libxslt1-dev libjpeg-dev zlib1g-dev
    libffi-dev libssl-dev
)

log "Packages to install: ${base_packages[*]}"
if [[ "$with_postgresql" == true ]]; then
    log "Requested PostgreSQL packages: postgresql-17 postgresql-client-17"
fi

if [[ "$apply" != true ]]; then
    warn "Dry plan only. Re-run with --apply after reviewing the package list."
    exit 0
fi

require_root
require_command apt-get
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${base_packages[@]}"

if [[ "$with_postgresql" == true ]]; then
    if apt-cache show postgresql-17 >/dev/null 2>&1 && apt-cache show postgresql-client-17 >/dev/null 2>&1; then
        DEBIAN_FRONTEND=noninteractive apt-get install -y postgresql-17 postgresql-client-17
    else
        die "PostgreSQL 17 packages are not available. Configure the official PGDG repository manually; this script will not add it silently."
    fi
fi

if command -v wkhtmltopdf >/dev/null 2>&1; then
    wk_version="$(wkhtmltopdf --version 2>&1 || true)"
    if [[ "$wk_version" == *"0.12.6"* ]]; then
        log "Compatible wkhtmltopdf detected: $wk_version"
    else
        warn "wkhtmltopdf is installed but is not verified as 0.12.6: $wk_version"
    fi
else
    warn "wkhtmltopdf is not installed. Install a verified Ubuntu-compatible 0.12.6 build manually."
    warn "No unverified binary was downloaded. See DEPLOYMENT_GUIDE.md."
fi

log "System dependencies installed. deploy.sh creates /opt/odoo/venv and installs /opt/odoo/odoo/requirements.txt."
log "The four custom addons have no additional external Python packages."
