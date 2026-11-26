#!/usr/bin/env bash
# Purge and reload one mailbox on a deployed environment (M13; run book in docs/go-live-channels.md).
#
#   scripts/mail_reload.sh <stage|prod> <mode> [mailbox] [days]
#
# draft-report: the T16 draft quality numbers of the last [days] (default 30); record them before a prod purge.
# preview:     counts what a purge would delete; only reads.
# purge:       after you type "purge <env> <mailbox>": worker stopped, database snapshot, purge, worker restored.
# reingest:    records the last [days] (default 90) of mail as held history; nothing is processed yet.
# run-history: puts the held mail on the history queue; the worker reads it overnight.
# status:      the reloaded mail by pipeline state; settle and draft-open refuse until none is held or pending.
# settle:      resolves cases quiet for [days] (tool default 14).
# draft-open:  dry run first; after you type "draft <env>", drafts mail of the last [days] (tool default 14).
# Only purge stops the worker. Needs the code deployed there and `aws login` with ECS, RDS and CloudWatch Logs access.
# Every report holds counts and ids only, never message text.
set -euo pipefail
# shellcheck source=lib/ecs_task.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/ecs_task.sh"

usage() {
  echo "usage: $0 <stage|prod> <draft-report|preview|purge|reingest|run-history|status|settle|draft-open> [mailbox] [days]" >&2
  exit 64
}

[ $# -ge 2 ] && [ $# -le 4 ] || usage
ENV_NAME=$1
MODE=$2
MAILBOX=${3:-info@hrrealestate.nl}
DAYS=${4:-}
case "$ENV_NAME" in stage | prod) ;; *) usage ;; esac
case "$MODE" in
  draft-report | reingest | settle | draft-open) ;;
  preview | purge | run-history | status) [ -z "$DAYS" ] || usage ;;
  *) usage ;;
esac
[[ "$MAILBOX" =~ ^[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+$ ]] || usage
[ -z "$DAYS" ] || [[ "$DAYS" =~ ^[1-9][0-9]{0,2}$ ]] || usage

DB_INSTANCE=${RELOAD_DB_INSTANCE:-estateos-${ENV_NAME}-db}
POLL_SECONDS=${RELOAD_POLL_SECONDS:-10}
RUN_ID="mail-reload-$(date -u +%y%m%d%H%M%S)-$$" # `startedBy` on our tasks, so cleanup finds any still running
TASK_KIND=reload
ecs_init

# run_mode <label> <tool argument>...: one task; fails when the tool fails.
run_mode() {
  local label=$1 command arg
  shift
  command="\"python\",\"-m\",\"app.workflows.mail_reload_cli\",\"--mailbox\",\"${MAILBOX}\""
  for arg in "$@"; do command+=",\"${arg}\""; done
  run_task "$label" "$command" || return 1
  [ "$TASK_EXIT" = 0 ] && return 0
  say "The tool failed (exit ${TASK_EXIT}); see the report above."
  return 1
}

draft_open() {
  local days=()
  if [ -n "$DAYS" ]; then days=(--max-age-days "$DAYS"); fi
  run_mode "draft-open dry run" --draft-open ${days[@]+"${days[@]}"} --dry-run
  echo "Read the list above. Drafts are offered to Harjot for approval; nothing is sent."
  confirm_typed "draft ${ENV_NAME}"
  run_mode draft-open --draft-open ${days[@]+"${days[@]}"}
}

settle() {
  if [ -n "$DAYS" ]; then
    run_mode settle --settle --idle-days "$DAYS"
  else
    run_mode settle --settle
  fi
}

if [ "$MODE" != purge ]; then
  trap_worker_running
  case "$MODE" in
    draft-report) run_mode draft-report --draft-report --days "${DAYS:-30}" ;;
    preview) run_mode preview --preview ;;
    status) run_mode status --status ;;
    reingest) run_mode reingest --reingest --days "${DAYS:-90}" ;;
    run-history) run_mode run-history --run-history ;;
    settle) settle ;;
    draft-open) draft_open ;;
  esac
  exit $?
fi

read_workers || exit 1
echo "This DELETES the stored Gmail mail of ${MAILBOX} on ${ENV_NAME}: messages, cases, drafts, approvals, documents."
echo "People, units, leases, WhatsApp, model calls and the send log stay. The files in Drive stay."
echo "The worker stops while it runs; the snapshot is of database ${DB_INSTANCE}."
echo "Record the draft report and run a preview first. Do not run during a deploy."
confirm_typed "purge ${ENV_NAME} ${MAILBOX}" || exit 1

stop_worker_and_snapshot reload
run_mode purge --purge --worker-stopped --confirm "purge ${MAILBOX}"
bring_worker_back
say "The worker is running again. Next: $0 ${ENV_NAME} reingest ${MAILBOX} 90"
