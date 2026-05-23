#!/usr/bin/env bash
set -euo pipefail

APP_NAME="public-node-admin"
DEFAULT_REPO="https://github.com/webhuage-debug/jiandiancaiji.git"
DEFAULT_BRANCH="codex/v1.0.0-release"
INSTALL_DIR="${INSTALL_DIR:-/opt/${APP_NAME}}"
GIT_REPO="${GIT_REPO:-$DEFAULT_REPO}"
GIT_BRANCH="${GIT_BRANCH:-$DEFAULT_BRANCH}"
APP_PORT="${APP_PORT:-3000}"
ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"
SESSION_SECRET="${SESSION_SECRET:-}"
PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-}"
SKIP_DOCKER_INSTALL="${SKIP_DOCKER_INSTALL:-false}"

need_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "Please run as root or with sudo."
    exit 1
  fi
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

random_secret() {
  if need_cmd openssl; then
    openssl rand -hex 32
  else
    tr -dc 'A-Za-z0-9' </dev/urandom | head -c 64
  fi
}

install_base_packages() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl gnupg git openssl
}

install_docker() {
  if need_cmd docker && docker compose version >/dev/null 2>&1; then
    return
  fi
  if [ "$SKIP_DOCKER_INSTALL" = "true" ]; then
    echo "Docker is not installed and SKIP_DOCKER_INSTALL=true."
    exit 1
  fi

  install -m 0755 -d /etc/apt/keyrings
  if [ ! -f /etc/apt/keyrings/docker.gpg ]; then
    curl -fsSL https://download.docker.com/linux/"$(. /etc/os-release && echo "$ID")"/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
  fi

  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/${ID} ${VERSION_CODENAME} stable" >/etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
}

clone_or_update_repo() {
  mkdir -p "$(dirname "$INSTALL_DIR")"

  local repo_url="$GIT_REPO"
  if [ -n "${GITHUB_TOKEN:-}" ] && [[ "$repo_url" == https://github.com/* ]]; then
    repo_url="${repo_url/https:\/\/github.com\//https:\/\/x-access-token:${GITHUB_TOKEN}@github.com\/}"
  fi

  if [ -d "$INSTALL_DIR/.git" ]; then
    git -C "$INSTALL_DIR" fetch origin "$GIT_BRANCH"
    git -C "$INSTALL_DIR" checkout "$GIT_BRANCH"
    git -C "$INSTALL_DIR" pull --ff-only origin "$GIT_BRANCH"
  else
    git clone --branch "$GIT_BRANCH" "$repo_url" "$INSTALL_DIR"
  fi
}

write_env() {
  cd "$INSTALL_DIR"
  if [ -f .env ]; then
    echo ".env already exists, keeping current runtime configuration."
    return
  fi

  if [ -z "$ADMIN_PASSWORD" ]; then
    ADMIN_PASSWORD="$(random_secret)"
    echo "Generated ADMIN_PASSWORD: $ADMIN_PASSWORD"
  fi
  if [ -z "$SESSION_SECRET" ]; then
    SESSION_SECRET="$(random_secret)"
  fi
  if [ -z "$PUBLIC_BASE_URL" ]; then
    PUBLIC_BASE_URL="http://$(hostname -I | awk '{print $1}'):${APP_PORT}"
  fi

  cat >.env <<EOF_ENV
NODE_ENV=production
APP_NAME=Public Node Admin
APP_HOST=0.0.0.0
APP_PORT=${APP_PORT}
PUBLIC_BASE_URL=${PUBLIC_BASE_URL}

ADMIN_USERNAME=${ADMIN_USERNAME}
ADMIN_PASSWORD=${ADMIN_PASSWORD}

SESSION_SECRET=${SESSION_SECRET}
SESSION_COOKIE_SECURE=auto
SESSION_TTL_HOURS=8
LOGIN_MAX_FAILURES=5
LOGIN_LOCK_MINUTES=15

DATA_DIR=/data
DATABASE_PATH=/data/app.db
EXPORT_DIR=/data/exports
LOG_LEVEL=info

COLLECT_MAX_CONCURRENCY=2
COLLECT_MIN_INTERVAL_MINUTES=60
COLLECT_DAILY_MAX_RUNS=6
HTTP_TIMEOUT_SECONDS=12
COLLECT_RETRY_COUNT=2
COLLECT_MAX_BYTES=1048576
PUBLIC_SOURCE_SEEDS=

TEST_CONNECT_TIMEOUT_SECONDS=5
TEST_BATCH_SIZE=100
DOWNLOAD_RATE_LIMIT_PER_MINUTE=6
EOF_ENV

  chmod 600 .env
}

start_app() {
  cd "$INSTALL_DIR"
  docker compose up -d --build
  docker compose ps
}

main() {
  need_root
  install_base_packages
  install_docker
  clone_or_update_repo
  write_env
  start_app

  echo
  echo "Deploy complete."
  echo "Install dir: $INSTALL_DIR"
  echo "Admin URL: ${PUBLIC_BASE_URL:-http://SERVER_IP:${APP_PORT}}"
  echo "Admin username: $ADMIN_USERNAME"
  echo "If a password was generated above, save it now. It is not stored in Git."
}

main "$@"
