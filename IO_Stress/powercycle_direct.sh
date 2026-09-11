#!/bin/bash
if [ -z "$BASH_VERSION" ]; then
    exec bash "$0" "$@"
fi

set -o pipefail
export LANG=C.UTF-8
export LC_ALL=C.UTF-8

cd "$(dirname "$0")"

chmod +x lib/* run_fio.sh >/dev/null 2>&1 || true
. lib/global_variable.sh
. lib/arguments.sh
. lib/init.sh
. lib/common.sh
. lib/fio.sh
. lib/diff.sh

arguments_parse "$@"
check_arguments

if [[ "$item" != "REBOOT" && "$item" != "DC" ]]; then
    echo "powercycle_direct.sh only supports reboot/dc, got item=$item"
    exit 2
fi

# One-shot: only the initial pytest/Jenkins trigger sets this. Resume must not.
export POWER_CYCLE_FORCE_ONCE=1
export POWER_CYCLE_COMMAND_GRACE="${POWER_CYCLE_COMMAND_GRACE:-90}"

command_log="$ResultLog/reboot_command.log"
if [[ "$item" == "DC" ]]; then
    command_log="$ResultLog/dc_command.log"
fi

echo "POWER_CYCLE_DIRECT_START item=$item LOOP=$LOOP flag=$flag disks=${specified_disk:-null}"
intializer
echo "$(date '+%F %T') [DIRECT] initialized item=$item LOOP=$LOOP flag=$flag disks=${specified_disk:-null}" | tee -a "$command_log"

info_check
info_rc=$?
echo "$(date '+%F %T') [DIRECT] machinecheck before finished rc=$info_rc" | tee -a "$command_log"
if [[ $info_rc -ne 0 ]]; then
    echo "ERROR: MachineCheck before FIO failed, rc=$info_rc" | tee -a "$command_log"
    if [[ "$flag" == "STOP" ]]; then
        collect_log
        teardown_powercycle_resume
        test_end "$info_rc"
    else
        echo "flag=NON-STOP: continue after MachineCheck before failure" | tee -a "$command_log"
    fi
fi

loop=0
beforeloop=0
Second=$(date +%s)

do_fio
fio_rc=$?
echo "$(date '+%F %T') [DIRECT] do_fio rc=$fio_rc" | tee -a "$command_log"
if [[ $fio_rc -ne 0 ]]; then
    collect_log
    teardown_powercycle_resume
    test_end "$fio_rc"
fi

info_diff
echo "$(date '+%F %T') [DIRECT] machinecheck after/diff finished" | tee -a "$command_log"

collect_powercycle_dmesg
echo "$(date '+%F %T') [DIRECT] dmesg captured for loop=${loop:-0}" | tee -a "$command_log"

do_reboot
reboot_rc=$?
echo "$(date '+%F %T') [DIRECT] do_reboot rc=$reboot_rc" | tee -a "$command_log"
if [[ $reboot_rc -eq 10 ]]; then
    collect_log
    teardown_powercycle_resume
    test_end 0
fi
if [[ $reboot_rc -ne 0 ]]; then
    collect_log
    teardown_powercycle_resume
    test_end "$reboot_rc"
fi
# Successful reboot/dc request exits inside do_reboot; reaching here is unexpected.
echo "$(date '+%F %T') [DIRECT] unexpected do_reboot rc=$reboot_rc" | tee -a "$command_log"
teardown_powercycle_resume
test_end 1
