#!/usr/bin/env bash

# Basic CLI smoke tests

set -u
set -o pipefail

readonly skip_status=200

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root_dir"

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  color_red=$'\033[31m'
  color_green=$'\033[32m'
  color_yellow=$'\033[33m'
  color_reset=$'\033[0m'
else
  color_red=""
  color_green=""
  color_yellow=""
  color_reset=""
fi

pass_symbol="${color_green}✓${color_reset}"
fail_symbol="${color_red}✗${color_reset}"
skip_symbol="${color_yellow}○${color_reset}"

scratch_dir="$(mktemp -d "${root_dir}/tmp_basic_checks.XXXXXX")"

cleanup() {
  rm -rf "$scratch_dir"
}

trap cleanup EXIT

export UV_CACHE_DIR="${UV_CACHE_DIR:-${root_dir}/.uv-cache}"
export TUOCHAT_CONFIG_DIR="${scratch_dir}/config"
export TUOCHAT_DATA_DIR="${scratch_dir}/data"
export TUOCHAT_GITLAB_HOST=""
export TUOCHAT_GITLAB_TOKEN=""

mkdir -p "$TUOCHAT_CONFIG_DIR" "$TUOCHAT_DATA_DIR"

pass_count=0
fail_count=0
skip_count=0
total_count=0
log_index=0

conversation_id=""
last_command=""
last_output=""

run_command() {
  ((log_index += 1))
  last_output="${scratch_dir}/check-${log_index}.log"
  printf -v last_command '%q ' "$@"
  "$@" >"$last_output" 2>&1
}

mark_skipped() {
  ((log_index += 1))
  last_command=""
  last_output="${scratch_dir}/skip-${log_index}.log"
  printf '%s\n' "$1" >"$last_output"
  return "$skip_status"
}

print_output() {
  if [[ ! -s "$last_output" ]]; then
    printf '  | (no output)\n'
    return
  fi
  sed 's/^/  | /' "$last_output"
}

run_check() {
  local name="$1"
  local check_function="$2"

  ((total_count += 1))

  if "$check_function"; then
    ((pass_count += 1))
    printf '%b %s\n' "$pass_symbol" "$name"
    return 0
  fi

  local status=$?
  if [[ "$status" -eq "$skip_status" ]]; then
    ((skip_count += 1))
    printf '%b %s\n' "$skip_symbol" "$name"
    print_output
    return 0
  fi

  ((fail_count += 1))
  printf '%b %s\n' "$fail_symbol" "$name"
  if [[ -n "$last_command" ]]; then
    printf '  Command: %s\n' "${last_command% }"
  fi
  print_output
  return 0
}

check_root_help() {
  run_command uv run python -m tuochat --help
}

check_version() {
  run_command uv run python -m tuochat --version
}

check_chat_help() {
  run_command uv run python -m tuochat chat --help
}

check_gui_help() {
  run_command uv run python -m tuochat gui --help
}

check_convo_help() {
  run_command uv run python -m tuochat convo --help
}

check_archive_help() {
  run_command uv run python -m tuochat archive --help
}

check_context_help() {
  run_command uv run python -m tuochat context --help
}

check_headless_help() {
  run_command uv run python -m tuochat headless --help
}

check_init_help() {
  run_command uv run python -m tuochat init --help
}

check_config() {
  run_command uv run python -m tuochat config json
}

check_doctor() {
  run_command uv run python -m tuochat doctor --format json
}

check_usage() {
  run_command uv run python -m tuochat usage --format json
}

check_context_files() {
  run_command uv run python -m tuochat context files --format json
}

check_context_skills() {
  run_command uv run python -m tuochat context skills --format json
}

check_context_templates() {
  run_command uv run python -m tuochat context templates --format json
}

check_context_custom_instructions() {
  run_command uv run python -m tuochat context custom-instructions --format json
}

check_headless_ask() {
  run_command \
    uv run python -m tuochat headless ask \
    --model eliza \
    --json \
    --no-stream \
    --system-prompt "Smoke test system prompt" \
    --output-file "${scratch_dir}/headless-response.txt" \
    "Hello from the smoke tests."

  local status=$?
  if [[ "$status" -ne 0 ]]; then
    return "$status"
  fi

  conversation_id="$(sed -n 's/.*"conversation_id": "\(.*\)".*/\1/p' "$last_output" | head -n 1)"
  if [[ -n "$conversation_id" ]]; then
    return 0
  fi

  printf 'Could not extract conversation_id from headless JSON output.\n' >>"$last_output"
  return 1
}

check_headless_continue() {
  if [[ -z "$conversation_id" ]]; then
    mark_skipped "Headless continue requires a conversation created by headless ask."
    return "$skip_status"
  fi

  run_command \
    uv run python -m tuochat headless continue "$conversation_id" \
    --model eliza \
    --json \
    --no-stream \
    "Follow up from the smoke tests."
}

check_convo_list() {
  run_command uv run python -m tuochat convo list --format json --limit 5
}

check_history() {
  run_command uv run python -m tuochat history --format json --limit 5
}

check_convo_search() {
  run_command uv run python -m tuochat convo search smoke --limit 5
}

check_search_alias() {
  run_command uv run python -m tuochat search smoke --limit 5
}

check_convo_export() {
  if [[ -z "$conversation_id" ]]; then
    mark_skipped "Conversation export requires a conversation created by headless ask."
    return "$skip_status"
  fi

  run_command uv run python -m tuochat convo export "$conversation_id"
}

check_export_alias() {
  if [[ -z "$conversation_id" ]]; then
    mark_skipped "Export alias requires a conversation created by headless ask."
    return "$skip_status"
  fi

  run_command uv run python -m tuochat export "$conversation_id"
}

check_convo_archive() {
  if [[ -z "$conversation_id" ]]; then
    mark_skipped "Conversation archive requires a conversation created by headless ask."
    return "$skip_status"
  fi

  run_command uv run python -m tuochat convo archive "$conversation_id"
}

check_convo_list_archived() {
  run_command uv run python -m tuochat convo list --archived --format json --limit 5
}

check_convo_unarchive() {
  if [[ -z "$conversation_id" ]]; then
    mark_skipped "Conversation unarchive requires a conversation created by headless ask."
    return "$skip_status"
  fi

  run_command uv run python -m tuochat convo unarchive "$conversation_id"
}

check_convo_delete() {
  if [[ -z "$conversation_id" ]]; then
    mark_skipped "Conversation delete requires a conversation created by headless ask."
    return "$skip_status"
  fi

  run_command uv run python -m tuochat convo delete "$conversation_id"
}

check_convo_resume_help() {
  run_command uv run python -m tuochat convo resume --help
}

check_resume_help() {
  run_command uv run python -m tuochat resume --help
}

check_convo_open_help() {
  run_command uv run python -m tuochat convo open --help
}

check_archive_bagit_update_help() {
  run_command uv run python -m tuochat archive bagit-update --help
}

check_archive_bagit_check_help() {
  run_command uv run python -m tuochat archive bagit-check --help
}

printf 'Running CLI smoke checks...\n'

run_check "tuochat --help" check_root_help
run_check "tuochat --version" check_version
run_check "tuochat chat --help" check_chat_help
run_check "tuochat gui --help" check_gui_help
run_check "tuochat convo --help" check_convo_help
run_check "tuochat archive --help" check_archive_help
run_check "tuochat context --help" check_context_help
run_check "tuochat headless --help" check_headless_help
run_check "tuochat init --help" check_init_help
run_check "tuochat config json" check_config
run_check "tuochat doctor --format json" check_doctor
run_check "tuochat usage --format json" check_usage
run_check "tuochat context files --format json" check_context_files
run_check "tuochat context skills --format json" check_context_skills
run_check "tuochat context templates --format json" check_context_templates
run_check "tuochat context custom-instructions --format json" check_context_custom_instructions
run_check "tuochat headless ask --model eliza" check_headless_ask
run_check "tuochat headless continue --model eliza" check_headless_continue
run_check "tuochat convo list --format json" check_convo_list
run_check "tuochat history --format json" check_history
run_check "tuochat convo search smoke" check_convo_search
run_check "tuochat search smoke" check_search_alias
run_check "tuochat convo export" check_convo_export
run_check "tuochat export" check_export_alias
run_check "tuochat convo archive" check_convo_archive
run_check "tuochat convo list --archived --format json" check_convo_list_archived
run_check "tuochat convo unarchive" check_convo_unarchive
run_check "tuochat convo delete" check_convo_delete
run_check "tuochat convo resume --help" check_convo_resume_help
run_check "tuochat resume --help" check_resume_help
run_check "tuochat convo open --help" check_convo_open_help
run_check "tuochat archive bagit-update --help" check_archive_bagit_update_help
run_check "tuochat archive bagit-check --help" check_archive_bagit_check_help

printf '\nSmoke check summary: %b %d passed, %b %d failed, %b %d skipped\n' \
  "$pass_symbol" "$pass_count" \
  "$fail_symbol" "$fail_count" \
  "$skip_symbol" "$skip_count"

if [[ "$fail_count" -gt 0 ]]; then
  exit 1
fi
