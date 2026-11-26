# One-off maintenance tasks on a deployed environment, sourced by scripts/repair_mail.sh and scripts/mail_reload.sh.
#
# The caller sets ENV_NAME (checked), POLL_SECONDS, DB_INSTANCE, RUN_ID and TASK_KIND ("repair", "reload"), then calls
# `ecs_init`. The task runs the worker's current image and configuration: its database, models and Google connection.
# Works under bash 3.2 (macOS) and `set -euo pipefail`.

MAX_POLLS=1080 # three hours at the default interval
MAX_STATUS_ERRORS=10 # an expired login makes every status check fail: stop early
OPEN_TASK=""
TASK_EXIT=""

# Never lets a lost terminal or a closed pipe stop the script at a message.
say() { /bin/echo "$@" >&2 || true; } # a separate process takes a failed write, not this shell

service_field() {
  aws ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" --query "services[0].$1" --output "$2"
}

task_field() {
  aws ecs describe-task-definition --task-definition "$TASK_DEF" \
    --query "taskDefinition.containerDefinitions[0].$1" --output text
}

ecs_init() {
  export AWS_REGION=${AWS_REGION:-eu-north-1}
  export AWS_PAGER=""
  CLUSTER="estateos-${ENV_NAME}-cluster"
  SERVICE="estateos-${ENV_NAME}-worker-service"
  TASK_DEF=$(service_field taskDefinition text)
  NETWORK=$(service_field networkConfiguration json)
  CONTAINER=$(task_field name)
  LOG_GROUP=$(task_field 'logConfiguration.options."awslogs-group"')
  LOG_PREFIX=$(task_field 'logConfiguration.options."awslogs-stream-prefix"')
}

show_report() {
  say "----- report -----"
  aws logs filter-log-events --log-group-name "$LOG_GROUP" \
    --log-stream-names "${LOG_PREFIX}/${CONTAINER}/${1##*/}" --query 'events[].[message]' --output text ||
    say "Could not read the report; look in log group ${LOG_GROUP}, task ${1##*/}."
  say "------------------"
}

# run_task <label> <command as JSON array items>: TASK_EXIT holds the container's exit code; 1 if it never finished.
run_task() {
  local label=$1 overrides task status="" polls=0 errors=0
  TASK_EXIT=""
  overrides="{\"containerOverrides\":[{\"name\":\"${CONTAINER}\",\"command\":[$2]}]}"
  task=$(aws ecs run-task --cluster "$CLUSTER" --task-definition "$TASK_DEF" --launch-type FARGATE \
    --started-by "$RUN_ID" --network-configuration "$NETWORK" --overrides "$overrides" \
    --query 'tasks[0].taskArn' --output text)
  if [ -z "$task" ] || [ "$task" = None ]; then
    say "The task did not start."
    return 1
  fi
  OPEN_TASK=$task
  say "Task ${task##*/} (${label}) started. Waiting for it to finish..."
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
  TASK_EXIT=$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$task" \
    --query 'tasks[0].containers[0].exitCode' --output text)
  sleep "$POLL_SECONDS" # the last log lines arrive after the task stops
  show_report "$task"
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
    say "THE WORKER IS LEFT STOPPED: a ${TASK_KIND} task (started by ${RUN_ID}) may still be running."
    say "Confirm it has stopped, then set ${SERVICE} back to ${WORKERS} task(s) by hand."
    exit 1
  fi
  restore_worker || code=1
  exit "$code"
}

# For tasks that run beside the worker: an interrupted script stops its own task and touches nothing else.
trap_worker_running() {
  trap 'stop_our_tasks || say "A task started by ${RUN_ID} may still be running."' EXIT
  trap 'exit 130' INT TERM HUP
}

# WORKERS = the worker tasks to come back to; fails when the service is already stopped.
read_workers() {
  WORKERS=$(service_field desiredCount text)
  if ! [[ "$WORKERS" =~ ^[1-9][0-9]*$ ]]; then
    say "The worker service is at ${WORKERS} task(s). Find out why before applying: nothing was done."
    return 1
  fi
}

# confirm_typed <expected answer>: fails unless exactly that is typed.
confirm_typed() {
  local answer
  printf 'Type "%s" to continue: ' "$1"
  read -r answer || answer=""
  if [ "$answer" != "$1" ]; then
    say "Not confirmed. Nothing was done."
    return 1
  fi
}

# stop_worker_and_snapshot <tag>: worker stopped (`cleanup` on every way out), old tasks gone, snapshot available.
stop_worker_and_snapshot() {
  local old_tasks snapshot
  old_tasks=$(aws ecs list-tasks --cluster "$CLUSTER" --service-name "$SERVICE" --query 'taskArns[]' --output text)
  [ "$old_tasks" != None ] || old_tasks=""
  trap cleanup EXIT
  trap 'exit 130' INT TERM HUP
  trap 'exit 141' PIPE
  say "Stopping the worker..."
  aws ecs update-service --cluster "$CLUSTER" --service "$SERVICE" --desired-count 0 >/dev/null
  aws ecs wait services-stable --cluster "$CLUSTER" --services "$SERVICE"
  # A stable service can still have an old task shutting down: wait for each one.
  if [ -n "$old_tasks" ]; then aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks $old_tasks; fi
  snapshot="${DB_INSTANCE}-before-mail-$1-$(date -u +%Y%m%d-%H%M%S)"
  say "Taking database snapshot ${snapshot} (delete it once the $1 is accepted: it holds all tenant data)..."
  aws rds create-db-snapshot --db-instance-identifier "$DB_INSTANCE" --db-snapshot-identifier "$snapshot" >/dev/null
  aws rds wait db-snapshot-available --db-snapshot-identifier "$snapshot"
}

# The worker back after the task, with the traps of a script whose tasks run beside it.
bring_worker_back() {
  trap - EXIT
  trap '' INT TERM HUP PIPE
  set +e
  restore_worker || exit 1
  trap - INT TERM HUP PIPE
  set -e
  trap_worker_running
}
