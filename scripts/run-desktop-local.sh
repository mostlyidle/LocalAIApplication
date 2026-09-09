#!/usr/bin/env bash
# Run one supervised local desktop-development session. Ollama is external and is never
# started, adopted, or stopped by this script.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Readiness and shutdown are deliberately bounded. curl's request timeout is shorter than
# the overall readiness budget so a dead listener cannot make the launcher hang indefinitely.
readonly READINESS_TIMEOUT_SECONDS=20
readonly READINESS_POLL_SECONDS=0.25
readonly CURL_CONNECT_TIMEOUT_SECONDS=0.5
readonly CURL_TOTAL_TIMEOUT_SECONDS=2
readonly SHUTDOWN_GRACE_SECONDS=5
readonly SHUTDOWN_POLL_SECONDS=0.1

backend_pid=""
backend_pgid=""
frontend_pid=""
frontend_pgid=""
tauri_pid=""
tauri_pgid=""
cleanup_done=0

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'Required command not found: %s\n' "$1" >&2
    return 1
  }
}

require_free_port() {
  if lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; then
    printf 'Port %s is already in use; refusing to adopt an unknown service.\n' "$1" >&2
    return 1
  fi
}

process_alive() {
  local pid="$1"
  local state=""
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  state="$(ps -o state= -p "$pid" 2>/dev/null | tr -d '[:space:]')"
  [[ -n "$state" && "$state" != Z* ]]
}

process_group_for() {
  ps -o pgid= -p "$1" 2>/dev/null | tr -d '[:space:]'
}

# Every owned root is made a session/process-group leader before it execs the real command.
# This lets cleanup signal only the process tree started by this invocation.
start_owned() {
  local name="$1"
  local working_directory="$2"
  shift 2

  (
    cd "$working_directory"
    exec python3 -c 'import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])' "$@"
  ) &
  local pid=$!
  local pgid=""
  for _ in {1..10}; do
    pgid="$(process_group_for "$pid")"
    [[ "$pgid" == "$pid" ]] && break
    sleep 0.05
  done
  if [[ "$pgid" != "$pid" ]]; then
    printf 'Could not establish an owned process group for %s.\n' "$name" >&2
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
    return 1
  fi

  printf -v "${name}_pid" '%s' "$pid"
  printf -v "${name}_pgid" '%s' "$pgid"
}

# Check the group membership from the kernel's process table, rather than using a broad
# process-name or port-based operation. The latter could terminate Ollama or an unrelated listener.
owned_group_alive() {
  local pgid="$1"
  [[ "$pgid" =~ ^[0-9]+$ ]] || return 1
  ps -axo pid=,pgid= 2>/dev/null | awk -v group="$pgid" '$2 == group { found = 1 } END { exit found ? 0 : 1 }'
}

signal_owned_group() {
  local signal="$1"
  local pgid="$2"
  if owned_group_alive "$pgid"; then
    /bin/kill "-$signal" -- "-$pgid" 2>/dev/null || true
  fi
}

cleanup_group() {
  local name="$1"
  local pid="$2"
  local pgid="$3"
  [[ "$pgid" =~ ^[0-9]+$ ]] || return 0
  owned_group_alive "$pgid" || return 0

  printf 'Stopping owned %s process group (%s) ...\n' "$name" "$pgid" >&2
  signal_owned_group TERM "$pgid"
  local polls=$((SHUTDOWN_GRACE_SECONDS * 10))
  for ((i = 0; i < polls; i++)); do
    owned_group_alive "$pgid" || break
    sleep "$SHUTDOWN_POLL_SECONDS"
  done

  if owned_group_alive "$pgid"; then
    printf 'Owned %s process group did not exit gracefully; escalating to KILL.\n' "$name" >&2
    signal_owned_group KILL "$pgid"
  fi
  # The group root is our direct child, so reap it without waiting on arbitrary descendants.
  [[ "$pid" =~ ^[0-9]+$ ]] && wait "$pid" 2>/dev/null || true
}

cleanup() {
  if [[ "$cleanup_done" -eq 1 ]]; then
    return 0
  fi
  cleanup_done=1
  # Only these three process groups were created by this invocation. Ollama and all other
  # listeners are intentionally outside the cleanup set.
  cleanup_group frontend "$frontend_pid" "$frontend_pgid"
  cleanup_group backend "$backend_pid" "$backend_pgid"
  cleanup_group tauri "$tauri_pid" "$tauri_pgid"
}

on_signal() {
  local signal="$1"
  local exit_code=143
  [[ "$signal" == "INT" ]] && exit_code=130
  printf 'Received %s; stopping the supervised desktop session.\n' "$signal" >&2
  exit "$exit_code"
}

health_is_ready() {
  python3 -c '
import json
import sys

try:
    payload = json.load(sys.stdin)
except (json.JSONDecodeError, TypeError):
    raise SystemExit(1)
raise SystemExit(0 if payload.get("meeting_ready") is True else 1)
' <<<"$1"
}

health_summary() {
  python3 -c '
import json
import sys

try:
    payload = json.load(sys.stdin)
except (json.JSONDecodeError, TypeError):
    print("invalid JSON health response")
else:
    print("status={!r} meeting_ready={!r}".format(payload.get("status"), payload.get("meeting_ready")))
' <<<"$1"
}

wait_ready() {
  local name="$1"
  local url="$2"
  local pid="$3"
  local started=$SECONDS
  local response=""
  local reason="no response"

  while ((SECONDS - started < READINESS_TIMEOUT_SECONDS)); do
    if ! process_alive "$pid"; then
      printf '%s died before readiness completed (pid %s).\n' "$name" "$pid" >&2
      return 1
    fi
    if response="$(curl --fail --silent --show-error \
      --connect-timeout "$CURL_CONNECT_TIMEOUT_SECONDS" \
      --max-time "$CURL_TOTAL_TIMEOUT_SECONDS" "$url" 2>/dev/null)"; then
      if [[ "$name" == "backend" ]]; then
        if health_is_ready "$response"; then
          return 0
        fi
        reason="$(health_summary "$response")"
      else
        return 0
      fi
    else
      reason="curl failed or exceeded its bounded timeout"
    fi
    sleep "$READINESS_POLL_SECONDS"
  done

  printf '%s readiness failed after %ss: %s\n' "$name" "$READINESS_TIMEOUT_SECONDS" "$reason" >&2
  if [[ "$name" == "backend" ]]; then
    printf 'The required readiness endpoint must report meeting_ready=true; HTTP 200 alone is insufficient.\n' >&2
  fi
  return 1
}

supervise() {
  while :; do
    if ! process_alive "$backend_pid"; then
      local status=1
      wait "$backend_pid" 2>/dev/null || status=$?
      printf 'Backend process exited unexpectedly (status %s).\n' "$status" >&2
      return 1
    fi
    if ! process_alive "$frontend_pid"; then
      local status=1
      wait "$frontend_pid" 2>/dev/null || status=$?
      printf 'Frontend process exited unexpectedly (status %s).\n' "$status" >&2
      return 1
    fi
    if ! process_alive "$tauri_pid"; then
      local status=0
      wait "$tauri_pid" 2>/dev/null || status=$?
      if [[ "$status" -ne 0 ]]; then
        printf 'Tauri process exited unexpectedly (status %s).\n' "$status" >&2
      fi
      return "$status"
    fi
    sleep "$READINESS_POLL_SECONDS"
  done
}

run_self_test() {
  require_command python3
  require_command ps
  require_command awk

  if health_is_ready '{"status":"degraded","meeting_ready":false}'; then
    printf 'self-test: rejected meeting_ready=false: FAIL\n' >&2
    return 1
  fi
  health_is_ready '{"status":"healthy","meeting_ready":true}'
  printf 'self-test: meeting_ready gate: OK\n'
  health_is_ready '{"status":"degraded","meeting_ready":true,"services":[{"name":"ollama","healthy":false,"optional_for_answers":true}]}'
  printf 'self-test: optional provider degradation accepted: OK\n'

  start_owned self "$root" sh -c 'trap "exit 0" TERM INT; (trap "exit 0" TERM INT; while :; do :; done) & wait'
  cleanup_group self "$self_pid" "$self_pgid"
  if owned_group_alive "$self_pgid"; then
    printf 'self-test: owned process-group cleanup: FAIL\n' >&2
    return 1
  fi
  printf 'self-test: owned process-group cleanup: OK\n'
}

trap cleanup EXIT
trap 'on_signal INT' INT
trap 'on_signal TERM' TERM

if [[ "${1:-}" == "--self-test" ]]; then
  run_self_test
  exit 0
fi
if [[ "$#" -ne 0 ]]; then
  printf 'Usage: %s [--self-test]\n' "${BASH_SOURCE[0]}" >&2
  exit 2
fi

require_command curl
require_command lsof
require_command python3
require_command ps
require_command awk
require_command uv
require_command pnpm
require_command cargo
require_free_port 8000
require_free_port 3000

cd "$root/backend"
uv run alembic upgrade head
start_owned backend "$root/backend" uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
wait_ready backend http://127.0.0.1:8000/api/v1/health/ready "$backend_pid"

start_owned frontend "$root/frontend" pnpm dev --hostname 127.0.0.1 --port 3000
wait_ready frontend http://127.0.0.1:3000 "$frontend_pid"

start_owned tauri "$root/desktop/src-tauri" cargo tauri dev
supervise
