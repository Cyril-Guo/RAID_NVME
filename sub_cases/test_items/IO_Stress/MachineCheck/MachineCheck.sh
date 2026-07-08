#!/bin/bash
export LANG=C.UTF-8
export LC_ALL=C.UTF-8
export TERM=linux
Cur_Dir=$(cd $(dirname $0)|pwd)
Result_Dir="$Cur_Dir/Result"

rm -rf $Result_Dir
rm -rf $Cur_Dir/*.log
rm -rf $Cur_Dir/*.txt
mkdir -p $Result_Dir

###########################################common function###################################################
show_produce_message() {
        local i
        tput bold >/dev/null 2>&1
        TEXT=$1
        length_text=${#TEXT}
        let length_title=80-length_text
        let half=length_title/2
        local str=""
        for ((i = 0; i < $half; i++)); do
                str="$str-"
        done
        TEXT="$str"$TEXT"$str"
        echo -ne "$TEXT"
        echo
}
show_fail_message() {
        tput bold >/dev/null 2>&1
        echo -ne "$@"
        echo
}
show_pass_message() {
        tput bold >/dev/null 2>&1
        echo -ne "$@"
        echo
}
show_item() {
        item_key="$1"
        item_value="$2"
        printf "%-25s\t\t\t\t%s\n" "$item_key" "$item_value"
}
show_title() {
        _TEXT=$@
        tput bold >/dev/null 2>&1
        echo -ne "[$_TEXT]"
        echo
}

###########################################function install tools###################################################

function install_systemtools()
{
    echo -e " *************************install system tools********************************  \n"
    if ! command -v nvme &> /dev/null; then
        if [[ -f /etc/os-release ]]; then
            source /etc/os-release
            case $ID in
                ubuntu|debian)
                    apt-get update >/dev/null
                    apt-get install -y nvme-cli >/dev/null
                    ;;
                centos|rocky|rhel|fedora)
                    yum install -y nvme-cli >/dev/null || dnf install -y nvme-cli >/dev/null
                    ;;
                *)
                    echo "Unsupported OS for automatic online installation. Please install nvme-cli manually."
                    ;;
            esac
        fi
    fi
    sleep 2
}

###########################################function tool ver###################################################
machine_info_check_tool_ver() {
        show_produce_message "Machine Information Checking tool version"
        show_item "MachineCheck Information" 
        show_title "Tool Version"
        show_item "nvme" "$(nvme --version 2>/dev/null)"
        show_produce_message "Machine Information Checking tool version"
}
###########################################function machine summary###################################################
machine_summary() {
        show_produce_message "Machine Summary Message"
	    cpu_model_name=$(lscpu | grep -iE 'model name' | uniq |  awk -F 'name:' '{print $NF}' | sed 's/^[ \t]*//;s/[ \t]*$//')
	    cpu_nums=$(lscpu | grep -i ^socket | awk -F':' '{print $NF}' | sed 's/[[:space:]]//g')
        show_item "cpu model name:" "$cpu_model_name"
        show_item "cpu numbers:" "$cpu_nums"

        nvme_count=$(nvme list 2>/dev/null | grep -c "^/dev/")
        show_item "NVME Numbers:" "$nvme_count"
        
        show_produce_message "Machine Summary Message"
}

# Execution
if [[ ! -f $Cur_Dir/install_flag ]]; then
    echo "First time run: ensuring tools are available."
    install_systemtools
    echo "done" > $Cur_Dir/install_flag
fi

machine_info_check_tool_ver >> $Result_Dir/machinecheck.log
machine_summary >> $Result_Dir/machinecheck.log


cat $Result_Dir/machinecheck.log
