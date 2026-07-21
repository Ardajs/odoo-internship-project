#!/usr/bin/env bash

# Shared helpers for the Odoo deployment scripts.
# This file is sourced; callers enable their own strict mode.

log() {
    printf '[INFO] %s\n' "$*"
}

warn() {
    printf '[WARN] %s\n' "$*" >&2
}

die() {
    printf '[ERROR] %s\n' "$*" >&2
    exit 1
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

require_command() {
    command_exists "$1" || die "Required command not found: $1"
}

require_root() {
    [[ "$(id -u)" -eq 0 ]] || die "Run this command as root (sudo)."
}

require_file() {
    local path="$1"
    [[ -f "$path" ]] || die "Required file not found: $path"
    [[ ! -L "$path" ]] || die "Required file must not be a symbolic link: $path"
}

secure_directory_check() {
    local path="$1"
    local expected_owner="${2:-root}"
    local expected_group="${3:-root}"
    local owner group mode

    [[ -d "$path" ]] || die "Secure directory not found: $path"
    [[ ! -L "$path" ]] || die "Secure directory must not be a symbolic link: $path"

    owner="$(stat -c '%U' "$path")"
    group="$(stat -c '%G' "$path")"
    mode="$(stat -c '%a' "$path")"
    [[ "$owner" == "$expected_owner" && "$group" == "$expected_group" ]] || \
        die "$path must be owned by $expected_owner:$expected_group (current: $owner:$group)."
    [[ "$mode" == "700" ]] || \
        die "$path must have mode 0700 (current mode: $mode)."
}

load_env() {
    local env_file="${1:-${ENV_FILE:-/etc/odoo/deployment.env}}"
    local mode group_digit other_digit owner

    [[ -f "$env_file" ]] || die "Environment file not found: $env_file"

    owner="$(stat -c '%U' "$env_file")"
    mode="$(stat -c '%a' "$env_file")"
    group_digit="${mode: -2:1}"
    other_digit="${mode: -1}"

    if [[ "$(id -u)" -eq 0 && "$owner" != "root" ]]; then
        die "$env_file must be owned by root before a privileged script sources it."
    fi
    if (( (10#$group_digit & 2) != 0 || (10#$other_digit & 2) != 0 )); then
        die "$env_file must not be group/world writable (current mode: $mode)."
    fi

    # The file is trusted only after the ownership and write-permission checks.
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
}

is_placeholder() {
    local value="${1:-}"
    [[ -z "$value" ||
       "$value" == "DATABASE_NAME" ||
       "$value" == "DOMAIN_NAME" ||
       "$value" == "SERVER_IP" ||
       "$value" == "GITHUB_REPO_URL" ||
       "$value" == CHANGE_ME* ||
       "$value" == *"ODOO_MASTER_PASSWORD"* ]]
}

require_value() {
    local name="$1"
    local value="${!name:-}"

    if is_placeholder "$value"; then
        die "$name is missing or still contains a placeholder."
    fi
}

require_absolute_safe_path() {
    local name="$1"
    local value="${!name:-}"
    [[ "$value" == /* && "$value" != "/" ]] || die "$name must be an absolute path other than / (current: $value)."
}

validate_database_name() {
    local value="$1"
    [[ "$value" =~ ^[a-zA-Z][a-zA-Z0-9_]{0,50}$ ]] || \
        die "Unsafe database name '$value'. Use letters, numbers and underscore; start with a letter."
}

confirm_exact() {
    local expected="$1"
    local prompt="$2"
    local answer

    [[ -t 0 ]] || die "Interactive confirmation is required. Run this command from a terminal."
    printf '%s\nType exactly: %s\n> ' "$prompt" "$expected"
    IFS= read -r answer
    [[ "$answer" == "$expected" ]] || die "Confirmation did not match; no action taken."
}

git_head_or_unknown() {
    local directory="$1"
    if [[ -d "$directory/.git" ]]; then
        git -C "$directory" rev-parse HEAD 2>/dev/null || printf 'unknown'
    else
        printf 'unknown'
    fi
}

service_is_active() {
    systemctl is-active --quiet "$1"
}
