#!/bin/bash
[[ -n "${_FIO_VERIFY_LOADED:-}" ]] && return 0
_FIO_VERIFY_LOADED=1

function fio_verify_strip_config_directives() {
    sed -i '/verify=/d' $Cur_Dir/configuration.tmp
    sed -i '/verify_fatal=/d' $Cur_Dir/configuration.tmp
    sed -i '/verify_dump=/d' $Cur_Dir/configuration.tmp
    sed -i '/verify_only=/d' $Cur_Dir/configuration.tmp
    sed -i '/do_verify=/d' $Cur_Dir/configuration.tmp
    sed -i '/size=/d' $Cur_Dir/configuration.tmp
    sed -i '/serialize_overlap/d' $Cur_Dir/configuration.tmp
}

function fio_verify_apply_mode_options() {
    local verify_mode="$1"
    local run_time="$2"

    sed -i '/runtime=/d' $Cur_Dir/configuration.tmp
    sed -i '/time_based/d' $Cur_Dir/configuration.tmp
    sed -i "9i serialize_overlap=1" $Cur_Dir/configuration.tmp
    sed -i "9i verify_dump=1" $Cur_Dir/configuration.tmp
    sed -i "9i verify_fatal=1" $Cur_Dir/configuration.tmp
    sed -i "9i verify=config_verify_type" $Cur_Dir/configuration.tmp
    if [[ "$verify_mode" == "VERIFY" ]]; then
        sed -i "9i size=config_size" $Cur_Dir/configuration.tmp
        sed -i "9i verify_only=1" $Cur_Dir/configuration.tmp
    elif [[ "$verify_mode" == "STRESS" ]]; then
        sed -i "9i size=config_size" $Cur_Dir/configuration.tmp
        sed -i "9i do_verify=0" $Cur_Dir/configuration.tmp
        sed -i "9i ramp_time=5" $Cur_Dir/configuration.tmp
        sed -i "9i norandommap" $Cur_Dir/configuration.tmp
        sed -i "9i randrepeat=0" $Cur_Dir/configuration.tmp
        sed -i "9i time_based" $Cur_Dir/configuration.tmp
        sed -i "9i runtime=${run_time}" $Cur_Dir/configuration.tmp
    else
        # FILL / legacy WRITE: sequential write full window before reboot.
        sed -i "9i size=config_size" $Cur_Dir/configuration.tmp
        sed -i "9i do_verify=0" $Cur_Dir/configuration.tmp
    fi
}

function fio_verify_substitute_job_placeholders() {
    local offset="$1"
    local io_size="$2"
    local verify_type="$3"
    local config_file="$4"

    sed -i "s/off_set/${offset}/" $Config_Dir/$config_file
    sed -i "s/config_size/${io_size}/" $Config_Dir/$config_file
    sed -i "s/config_verify_type/${verify_type}/" $Config_Dir/$config_file
    # Job sections default to size=100%; keep verify slices from overlapping.
    sed -i "s#^size=100%\$#size=${io_size}#" $Config_Dir/$config_file
}
