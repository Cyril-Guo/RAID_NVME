#!/usr/bin/env bash
# Read-only snapshot. Each probe and the caller's SSH session have deadlines.
set -u
probe() {
    printf '\n[PROBE] %s\n' "$1"
    shift
    timeout --kill-after=1s 4s "$@" 2>&1
    printf '[PROBE_END] rc=%s\n' "$?"
}
probe timestamp date -Is
probe load cat /proc/loadavg
probe processes ps -eo pid,ppid,stat,wchan:32,etime,comm
probe kernel_log bash -c 'dmesg --ctime | tail -n 200'
count=0
while read -r pid; do
    [[ "$pid" =~ ^[0-9]+$ ]] || continue
    count=$((count + 1))
    [ "$count" -le 12 ] || break
    probe "task_${pid}" bash -c 'for file in status wchan stack; do printf "\n%s\n" "$file"; cat "/proc/$1/$file"; done' _ "$pid"
done < <(pgrep -x 'fio|dpraid|python3|nvme' || true)
printf '\n[NOTE] Task stacks may require root. Missing data or SSH timeout is recorded by the controller.\n'
