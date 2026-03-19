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

backup

autologin

#install_HPL
#install_fio

info_check


fio_cycle


