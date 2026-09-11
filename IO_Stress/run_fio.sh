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
        test_end
        exit $fio_rc
    fi

    info_diff

    collect_powercycle_dmesg
    echo "$(date '+%F %T') [RESUME] dmesg captured for loop=${loop:-0}"

    do_reboot
    reboot_rc=$?
    if [ $reboot_rc -eq 2 ]; then
        echo "Power-cycle test completed all $LOOP loops."
        collect_log
        if command -v systemctl >/dev/null 2>&1; then
            systemctl disable raid-nvme-powercycle-resume.service >/dev/null 2>&1
            rm -f /etc/systemd/system/raid-nvme-powercycle-resume.service
            rm -f "$Cur_Dir/powercycle_resume.sh"
            systemctl daemon-reload >/dev/null 2>&1
        fi
        test_end
    elif [ $reboot_rc -ne 0 ]; then
        exit $reboot_rc
    fi

elif [ "$item_" = "RESTORE" ];then
    restore
    echo "Restore and cleanup complete."
    exit 0
else
    echo "PowerCycle run_fio.sh only supports REBOOT/DC/RESTORE, got item=$item_"
    exit 1
fi

collect_log

test_end
