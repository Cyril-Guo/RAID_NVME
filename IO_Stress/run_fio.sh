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

# restore - Removed from here to prevent deleting the service file during active test cycles.


arguments_accept "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" "$9" "${10}" "${11}" "${12}" "${13}" "${14}" "${15}" "${16}" "${17}" "${18}" "${19}" "${20}" "${21}" "${22}"

count_time


#echo "${20};;${21}"
#echo 22222222222222222222
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

    do_reboot || exit $?

elif [ "$item_" = "LAWDISKSTRESS" ] || [ "$item_" = "FILESYSTEMSTRESS" ];then

    do_fio
    fio_rc=$?
    if [ $fio_rc -ne 0 ]; then
        echo "FIO stage failed in $item_ mode, rc=$fio_rc"
        collect_log
        test_end
        exit $fio_rc
    fi

    info_diff
    #do_reboot
elif [ "$item_" = "RESTORE" ];then
    restore
    echo "Restore and cleanup complete."
    exit 0
else
    echo "not support mode,exit"
    exit 1
fi

collect_log

test_end
