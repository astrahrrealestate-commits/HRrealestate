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

usage() { echo "usage: $0 <stage|prod> <preview|apply|label> [mailbox]" >&2; exit 64; }
# Never lets a lost terminal or a closed pipe stop the script at a message.
say() { /bin/echo "$@" >&2 || true; } # a separate process takes a failed write, not this shell

[ $# -ge 2 ] && [ $# -le 3 ] || usage
ENV_NAME=$1
MODE=$2
MAILBOX=${3:-info@hrrealestate.nl}
case "$ENV_NAME" in stage | prod) ;; *) usage ;; esac
case "$MODE" in preview | apply | label) ;; *) usage ;; esac
[[ "$MAILBOX" =~ ^[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+$ ]] || usage

export AWS_REGION=${AWS_REGION:-eu-north-1}
export AWS_PAGER=""
CLUSTER="estateos-${ENV_NAME}-cluster"
SERVICE="estateos-${ENV_NAME}-worker-service"
DB_INSTANCE=${REPAIR_DB_INSTANCE:-estateos-${ENV_NAME}-db}
POLL_SECONDS=${REPAIR_POLL_SECONDS:-10}
MAX_POLLS=1080 # three hours at the default interval
MAX_STATUS_ERRORS=10 # an expired login makes every status check fail: stop early
RUN_ID="mail-repair-$(date -u +%y%m%d%H%M%S)-$$" # `startedBy` on our tasks, so cleanup finds any still running
OPEN_TASK=""

service_field() {
  aws ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" --query "services[0].$1" --output "$2"
}

# The tool runs the image and configuration the worker runs now: its database, model and Google connection.
TASK_DEF=$(service_field taskDefinition text)
NETWORK=$(service_field networkConfiguration json)
task_field() {
  aws ecs describe-task-definition --task-definition "$TASK_DEF" \
    --query "taskDefinition.containerDefinitions[0].$1" --output text
}
CONTAINER=$(task_field name)
LOG_GROUP=$(task_field 'logConfiguration.options."awslogs-group"')
LOG_PREFIX=$(task_field 'logConfiguration.options."awslogs-stream-prefix"')

show_report() {
  say "----- report -----"
  aws logs filter-log-events --log-group-name "$LOG_GROUP" \
    --log-stream-names "${LOG_PREFIX}/${CONTAINER}/${1##*/}" --query 'events[].[message]' --output text ||
    say "Could not read the report; look in log group ${LOG_GROUP}, task ${1##*/}."
  say "------------------"
}

# run_tool <preview|apply|label>: 0 done, 2 the labelling did not finish, 1 anything else.
run_tool() {
  local step=$1 command overrides task status="" code polls=0 errors=0
  command="\"python\",\"-m\",\"app.workflows.reattribute_cli\",\"--mailbox\",\"${MAILBOX}\""
  case "$step" in
    apply) command+=",\"--apply\",\"--worker-stopped\"" ;;
    label) command+=",\"--label\"" ;;
  esac
  overrides="{\"containerOverrides\":[{\"name\":\"${CONTAINER}\",\"command\":[${command}]}]}"
  task=$(aws ecs run-task --cluster "$CLUSTER" --task-definition "$TASK_DEF" --launch-type FARGATE \
    --started-by "$RUN_ID" --network-configuration "$NETWORK" --overrides "$overrides" \
    --query 'tasks[0].taskArn' --output text)
  if [ -z "$task" ] || [ "$task" = None ]; then
    say "The task did not start."
    return 1
  fi
  OPEN_TASK=$task
  say "Task ${task##*/} (${step}) started. Waiting for it to finish..."
  while [ "$status" != STOPPED ]; do
    polls=$((polls + 1))
    if [ "$polls" -gt "$MAX_POLLS" ] || [ "$errors" -ge "$MAX_STATUS_ERRORS" ]; then
      say "Giving up on the task: it ran too long, or its status cannot be read (has the AWS login expired?)."
      show_report "$task"
      return 1
    fi
    sleep "$POLL_SECONDS"
    if status=$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$task" \
      --query 'tasks[0].lastStatus' --output text); then
      errors=0
    else
      status="" errors=$((errors + 1))
    fi
  done
  OPEN_TASK=""
  code=$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$task" \
    --query 'tasks[0].containers[0].exitCode' --output text)
  sleep "$POLL_SECONDS" # the last log lines arrive after the task stops
  show_report "$task"
  case "$code" in
    0) return 0 ;;
    2)
      say "Labelling did not finish. Run: $0 ${ENV_NAME} label"
      return 2
      ;;
    *)
      say "The tool failed (exit ${code}). Before restoring any snapshot, check the report for APPLIED:"
      say "if it is there, the repair was saved."
      return 1
      ;;
  esac
}

# Stops every task of this run that may still be running. Fails unless they are confirmed stopped.
stop_our_tasks() {
  local listed task tasks
  listed=$(aws ecs list-tasks --cluster "$CLUSTER" --started-by "$RUN_ID" --query 'taskArns[]' --output text) ||
    return 1
  [ "$listed" = None ] && listed=""
  tasks=$(printf '%s\n' $listed $OPEN_TASK | sort -u)
  [ -n "$tasks" ] || return 0
  for task in $tasks; do
    aws ecs stop-task --cluster "$CLUSTER" --task "$task" >/dev/null || return 1
  done
  aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks $tasks || return 1
  OPEN_TASK=""
}

restore_worker() {
  local attempt
  for attempt in 1 2 3; do
    if aws ecs update-service --cluster "$CLUSTER" --service "$SERVICE" --desired-count "$WORKERS" >/dev/null; then
      say "The worker is set back to ${WORKERS} task(s)."
      return 0
    fi
    sleep "$POLL_SECONDS"
  done
  say "COULD NOT RESTORE THE WORKER: set ${SERVICE} back to ${WORKERS} task(s) by hand."
  return 1
}

# Runs on every way out while the worker is stopped. A second Ctrl-C or a lost terminal cannot cut it short.
cleanup() {
  local code=$?
  trap - EXIT
  trap '' INT TERM HUP PIPE
  set +e
  if ! stop_our_tasks; then
    say "THE WORKER IS LEFT STOPPED: a repair task (started by ${RUN_ID}) may still be running."
    say "Confirm it has stopped, then set ${SERVICE} back to ${WORKERS} task(s) by hand."
    exit 1
  fi
  restore_worker || code=1
  exit "$code"
}

if [ "$MODE" != apply ]; then
  trap 'stop_our_tasks || say "A task started by ${RUN_ID} may still be running."' EXIT
  trap 'exit 130' INT TERM HUP
  run_tool "$MODE"
  exit $?
fi

WORKERS=$(service_field desiredCount text)
if ! [[ "$WORKERS" =~ ^[1-9][0-9]*$ ]]; then
  say "The worker service is at ${WORKERS} task(s). Find out why before applying: nothing was done."
  exit 1
fi
echo "This changes stored mail on ${ENV_NAME} for ${MAILBOX} and cancels unsent replies on affected cases."
echo "The worker stops while it runs; the snapshot is of database ${DB_INSTANCE}."
echo "Run a preview first. Do not draft replies from the dashboard until this ends. Do not run during a deploy."
printf 'Type "apply %s" to continue: ' "$ENV_NAME"
read -r answer || answer=""
if [ "$answer" != "apply ${ENV_NAME}" ]; then
  say "Not confirmed. Nothing was done."
  exit 1
fi

OLD_TASKS=$(aws ecs list-tasks --cluster "$CLUSTER" --service-name "$SERVICE" --query 'taskArns[]' --output text)
[ "$OLD_TASKS" != None ] || OLD_TASKS=""
trap cleanup EXIT
trap 'exit 130' INT TERM HUP
trap 'exit 141' PIPE

say "Stopping the worker..."
aws ecs update-service --cluster "$CLUSTER" --service "$SERVICE" --desired-count 0 >/dev/null
aws ecs wait services-stable --cluster "$CLUSTER" --services "$SERVICE"
# A stable service can still have an old task shutting down: wait for each one.
if [ -n "$OLD_TASKS" ]; then aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks $OLD_TASKS; fi

SNAPSHOT="${DB_INSTANCE}-before-mail-repair-$(date -u +%Y%m%d-%H%M%S)"
say "Taking database snapshot ${SNAPSHOT} (delete it once the repair is accepted: it holds all tenant data)..."
aws rds create-db-snapshot --db-instance-identifier "$DB_INSTANCE" --db-snapshot-identifier "$SNAPSHOT" >/dev/null
aws rds wait db-snapshot-available --db-snapshot-identifier "$SNAPSHOT"

run_tool apply

trap - EXIT
trap '' INT TERM HUP PIPE
set +e
restore_worker || exit 1
trap - INT TERM HUP PIPE
set -e
trap 'stop_our_tasks || say "A task started by ${RUN_ID} may still be running."' EXIT
trap 'exit 130' INT TERM HUP
say "Adding the labels. The worker is running again; new mail is processed as usual."
run_tool label
