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

if [[ $item == "RESTORE" ]];then
    restore
    exit 0
fi

intializer
#######################

# Stress paths (lawdisk/filesystem/mix) must not rewrite getty/tty login policy.
# Reboot/dc use powercycle_direct.sh + autoopen instead.

#install_HPL
#install_fio

echo "[STAGE] item=${item} phase=machinecheck_before start"
info_check
machinecheck_rc=$?
if [[ $machinecheck_rc -ne 0 ]]; then
    echo "[STAGE] item=${item} phase=machinecheck_before failed rc=${machinecheck_rc}"
    exit "$machinecheck_rc"
fi
echo "[STAGE] item=${item} phase=machinecheck_before finish rc=0"


echo "[STAGE] item=${item} phase=fio_cycle start"
fio_cycle


