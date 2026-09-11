#!/bin/bash
if [ -z "$BASH_VERSION" ]; then
    exec bash "$0" "$@"
fi
export LANG=C.UTF-8
export LC_ALL=C.UTF-8

chmod +x lib/*
. lib/global_variable.sh
. lib/arguments.sh
. lib/init.sh
. lib/common.sh
. lib/fio.sh

arguments_parse "$@"
check_arguments

if [[ $item == "RESTORE" ]]; then
    restore
    exit 0
fi

echo "Fio_All.sh on PowerCycle branch only supports -i restore (got item=$item)."
echo "Use powercycle_direct.sh / run_fio.sh for reboot/dc."
exit 1
