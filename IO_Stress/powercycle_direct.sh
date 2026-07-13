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

arguments_parse "$@"
check_arguments

if [[ "$item" != "REBOOT" && "$item" != "DC" ]]; then
    echo "powercycle_direct.sh only supports reboot/dc, got item=$item"
    exit 2
fi

export POWER_CYCLE_FORCE_ONCE=1

command_log="$ResultLog/reboot_command.log"
if [[ "$item" == "DC" ]]; then
    command_log="$ResultLog/dc_command.log"
fi

echo "POWER_CYCLE_DIRECT_START item=$item LOOP=$LOOP flag=$flag disks=${specified_disk:-null}"
intializer
echo "$(date '+%F %T') [DIRECT] initialized item=$item LOOP=$LOOP flag=$flag disks=${specified_disk:-null}" | tee -a "$command_log"

info_check
echo "$(date '+%F %T') [DIRECT] machinecheck before finished" | tee -a "$command_log"

loop=0
beforeloop=0
Second=$(date +%s)

do_fio
fio_rc=$?
echo "$(date '+%F %T') [DIRECT] do_fio rc=$fio_rc" | tee -a "$command_log"
if [[ $fio_rc -ne 0 ]]; then
    collect_log
    test_end
    exit $fio_rc
fi

do_reboot
reboot_rc=$?
echo "$(date '+%F %T') [DIRECT] do_reboot rc=$reboot_rc" | tee -a "$command_log"
if [[ $reboot_rc -eq 2 ]]; then
    collect_log
    test_end
fi
exit $reboot_rc
