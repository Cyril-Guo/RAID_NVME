#!/bin/bash
if [ -z "$BASH_VERSION" ]; then
    exec bash "$0" "$@"
fi

# Change to the script's directory to ensure relative paths work
cd "$(dirname "$0")"

chmod +x lib/*
. lib/global_variable.sh
. lib/common.sh
. lib/fio.sh
. lib/diff.sh
. lib/init.sh

dotrap

arguments_accept "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" "$9" "${10}" "${11}" "${12}" "${13}" "${14}" "${15}" "${16}" "${17}" "${18}" "${19}" "${20}" "${21}" "${22}"

count_time

item_=$1

show_produce_message "start do Fio $item_"
sleep 3
if [ "$item_" == "DC" ] || [ "$item_" == "REBOOT" ] ;then
    do_fio
    fio_rc=$?
    if [ $fio_rc -ne 0 ]; then
        echo "FIO stage failed in $item_ mode, rc=$fio_rc"
        collect_log
        teardown_powercycle_resume
        test_end "$fio_rc"
    fi

    info_diff
    # info_diff may call test_end 3 on MachineCheck STOP; if it returns, continue.

    collect_powercycle_dmesg
    echo "$(date '+%F %T') [RESUME] dmesg captured for loop=${loop:-0}"

    do_reboot
    reboot_rc=$?
    if [ $reboot_rc -eq 10 ]; then
        echo "Power-cycle test completed all $LOOP loops."
        collect_log
        teardown_powercycle_resume
        test_end 0
    elif [ $reboot_rc -ne 0 ]; then
        echo "Power-cycle reboot/dc command failed, rc=$reboot_rc"
        collect_log
        teardown_powercycle_resume
        test_end "$reboot_rc"
    else
        # Successful reboot/dc must exit inside do_reboot; rc=0 here is illegal.
        echo "ERROR: unexpected do_reboot rc=$reboot_rc (expected exit 0 inside do_reboot or return 10)"
        collect_log
        teardown_powercycle_resume
        test_end 1
    fi

elif [ "$item_" = "RESTORE" ];then
    restore
    echo "Restore and cleanup complete."
    exit 0
else
    echo "PowerCycle run_fio.sh only supports REBOOT/DC/RESTORE, got item=$item_"
    exit 1
fi

# REBOOT/DC paths always test_end/exit above; reaching here is unexpected.
echo "ERROR: run_fio.sh reached unexpected fallthrough for item=$item_"
collect_log
teardown_powercycle_resume
test_end 1
