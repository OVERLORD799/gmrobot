#!/usr/bin/env bash
# Push/fetch GMRobot via gh-proxy.org when Git 2.34 sends Bearer for ghp_ PATs.
#
# Token in /root/.github_token remains valid (GitHub API accepts it). gh-proxy's
# Git HTTP endpoints require Basic auth; Git 2.34.1 uses Authorization: Bearer for
# classic PATs, which gh-proxy rejects (401 invalid credentials). This script starts
# a short-lived local HTTP proxy on 127.0.0.1 that rewrites Bearer -> Basic and
# forwards to gh-proxy.org. It does not source the token file wholesale and does not
# change git config (only per-invocation -c credential.helper=).
#
# Usage:
#   scripts/git_push_gh_proxy.sh          # push current branch -> origin main
#   scripts/git_push_gh_proxy.sh fetch  # update refs/remotes/origin/main
#   scripts/git_push_gh_proxy.sh push   # same as default

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOKEN_FILE="${GITHUB_TOKEN_FILE:-/root/.github_token}"
PROXY_HOST="${GIT_GH_PROXY_HOST:-127.0.0.1}"
PROXY_PORT="${GIT_GH_PROXY_PORT:-18743}"
UPSTREAM_HOST="${GIT_GH_PROXY_UPSTREAM:-gh-proxy.org}"

read_github_var() {
  local key="$1"
  grep "^${key}=" "$TOKEN_FILE" | head -1 | cut -d= -f2- | tr -d $'\r\n" '
}

GITHUB_TOKEN="$(read_github_var GITHUB_TOKEN)"
GITHUB_USER="$(read_github_var GITHUB_USER)"
GITHUB_REPO="$(read_github_var GITHUB_REPO)"

if [[ -z "$GITHUB_TOKEN" || -z "$GITHUB_REPO" ]]; then
  echo "error: GITHUB_TOKEN and GITHUB_REPO required in $TOKEN_FILE" >&2
  exit 1
fi

PROXY_PID=""
cleanup() {
  if [[ -n "$PROXY_PID" ]] && kill -0 "$PROXY_PID" 2>/dev/null; then
    kill "$PROXY_PID" 2>/dev/null || true
    wait "$PROXY_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

start_bearer_basic_proxy() {
  export _GH_PROXY_TOKEN="$GITHUB_TOKEN"
  export _GH_PROXY_PORT="$PROXY_PORT"
  export _GH_PROXY_UPSTREAM="$UPSTREAM_HOST"
  python3 - <<'PY' &
import base64
import http.client
import os
import ssl
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = os.environ["_GH_PROXY_TOKEN"]
PORT = int(os.environ["_GH_PROXY_PORT"])
TARGET = os.environ["_GH_PROXY_UPSTREAM"]
BASIC = base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._proxy()

    def do_POST(self):
        self._proxy()

    def _proxy(self):
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            auth = f"Basic {BASIC}"
        body = None
        if self.command == "POST":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
        ctx = ssl.create_default_context()
        conn = http.client.HTTPSConnection(TARGET, context=ctx, timeout=300)
        skip = {"host", "authorization", "connection", "proxy-connection", "content-length"}
        headers = {k: v for k, v in self.headers.items() if k.lower() not in skip}
        headers["Host"] = TARGET
        headers["Authorization"] = auth
        if body is not None:
            headers["Content-Length"] = str(len(body))
        conn.request(self.command, self.path, body=body, headers=headers)
        resp = conn.getresponse()
        self.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() in ("transfer-encoding", "connection"):
                continue
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(resp.read())
        except BrokenPipeError:
            pass
        conn.close()

    def log_message(self, *args):
        pass


srv = HTTPServer((os.environ.get("_GH_PROXY_BIND", "127.0.0.1"), PORT), Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
threading.Event().wait()
PY
  PROXY_PID=$!
  local ready=0
  for _ in $(seq 1 50); do
    if ! kill -0 "$PROXY_PID" 2>/dev/null; then
      echo "error: Bearer->Basic proxy exited early" >&2
      exit 1
    fi
    if ss -ltn 2>/dev/null | grep -q ":${PROXY_PORT} "; then
      ready=1
      break
    fi
    sleep 0.1
  done
  if [[ "$ready" -ne 1 ]]; then
    echo "error: proxy did not listen on ${PROXY_HOST}:${PROXY_PORT}" >&2
    exit 1
  fi
}

git_via_proxy() {
  GIT_TERMINAL_PROMPT=0 git -C "$ROOT" -c credential.helper= "$@"
}

proxy_git_url() {
  # Git sends Bearer for ghp_; local proxy converts to Basic for gh-proxy.
  printf 'http://x-access-token:%s@%s:%s/https://github.com/%s.git' \
    "$GITHUB_TOKEN" "$PROXY_HOST" "$PROXY_PORT" "$GITHUB_REPO"
}

cmd="${1:-push}"
start_bearer_basic_proxy
GIT_URL="$(proxy_git_url)"

case "$cmd" in
  fetch)
    echo "Fetching refs/heads/main -> refs/remotes/origin/main via gh-proxy..."
    git_via_proxy fetch "$GIT_URL" "+refs/heads/main:refs/remotes/origin/main"
    echo "origin/main is now $(git -C "$ROOT" rev-parse refs/remotes/origin/main)"
    ;;
  push)
    branch="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)"
    echo "Pushing ${branch} -> main via gh-proxy (user ${GITHUB_USER:-unknown})..."
    git_via_proxy push "$GIT_URL" "HEAD:refs/heads/main"
    ;;
  *)
    echo "usage: $0 [fetch|push]" >&2
    exit 2
    ;;
esac
