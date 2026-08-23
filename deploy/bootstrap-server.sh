#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/opt/enrui-ai-commerce-agent/repository"
REPO_URL="https://github.com/Dreamsmama/enrui-ai-commerce-agent.git"
BRANCH="${DEPLOY_BRANCH:-main}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "请使用 root 执行"
  exit 1
fi

if ! command -v git >/dev/null; then
  apt-get update
  apt-get install -y git ca-certificates
fi

mkdir -p "$(dirname "$APP_DIR")"
if [[ ! -d "$APP_DIR/.git" ]]; then
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
exec bash "$APP_DIR/deploy.sh"
