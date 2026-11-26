#!/usr/bin/env bash
# One-time repair of forwarded mail on a deployed environment (ADR 0016).
#
#   scripts/repair_mail.sh <stage|prod> <preview|apply|label> [mailbox]
#
# preview: runs the tool in a one-off task with the worker's configuration; no mail changes, no model calls.
# apply:   after you type "apply <env>": worker stopped, database snapshot, repair, worker restored, then the labels.
# label:   the label pass alone (to finish one that stopped); the worker keeps running.
# Needs the code deployed to that environment and `aws login` with ECS, RDS and CloudWatch Logs access.
# The report holds names and email addresses and stays in the environment's CloudWatch logs.
set -euo pipefail
# shellcheck source=lib/ecs_task.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/ecs_task.sh"

usage() { echo "usage: $0 <stage|prod> <preview|apply|label> [mailbox]" >&2; exit 64; }

[ $# -ge 2 ] && [ $# -le 3 ] || usage
ENV_NAME=$1
MODE=$2
MAILBOX=${3:-info@hrrealestate.nl}
case "$ENV_NAME" in stage | prod) ;; *) usage ;; esac
case "$MODE" in preview | apply | label) ;; *) usage ;; esac
[[ "$MAILBOX" =~ ^[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+$ ]] || usage

DB_INSTANCE=${REPAIR_DB_INSTANCE:-estateos-${ENV_NAME}-db}
POLL_SECONDS=${REPAIR_POLL_SECONDS:-10}
RUN_ID="mail-repair-$(date -u +%y%m%d%H%M%S)-$$" # `startedBy` on our tasks, so cleanup finds any still running
TASK_KIND=repair
ecs_init

# run_tool <preview|apply|label>: 0 done, 2 the labelling did not finish, 1 anything else.
run_tool() {
  local step=$1 command
  command="\"python\",\"-m\",\"app.workflows.reattribute_cli\",\"--mailbox\",\"${MAILBOX}\""
  case "$step" in
    apply) command+=",\"--apply\",\"--worker-stopped\"" ;;
    label) command+=",\"--label\"" ;;
  esac
  run_task "$step" "$command" || return 1
  case "$TASK_EXIT" in
    0) return 0 ;;
    2)
      say "Labelling did not finish. Run: $0 ${ENV_NAME} label"
      return 2
      ;;
    *)
      say "The tool failed (exit ${TASK_EXIT}). Before restoring any snapshot, check the report for APPLIED:"
      say "if it is there, the repair was saved."
      return 1
      ;;
  esac
}

if [ "$MODE" != apply ]; then
  trap_worker_running
  run_tool "$MODE"
  exit $?
fi

read_workers || exit 1
echo "This changes stored mail on ${ENV_NAME} for ${MAILBOX} and cancels unsent replies on affected cases."
echo "The worker stops while it runs; the snapshot is of database ${DB_INSTANCE}."
echo "Run a preview first. Do not draft replies from the dashboard until this ends. Do not run during a deploy."
confirm_typed "apply ${ENV_NAME}" || exit 1

stop_worker_and_snapshot repair
run_tool apply
bring_worker_back
say "Adding the labels. The worker is running again; new mail is processed as usual."
run_tool label
