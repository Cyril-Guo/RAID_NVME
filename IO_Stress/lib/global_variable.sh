#!/bin/bash
export LANG=C.UTF-8
export LC_ALL=C.UTF-8
product_name=`dmidecode -t system|grep -i "Product Name"|awk -F ":" '{print $2}'|sed 's/ //g'|head -1` > /dev/null
if [[ $product_name == "" ]];then
   product_name="SUT"
fi

# Preferred snake_case directory names.
cur_dir=$(cd "$(dirname "$0")";pwd)
cp_root_dir=$cur_dir
job_dir=$cur_dir/job_files
log_ad=$cur_dir/log
test_error_log=$log_ad/TestErrorLog
result_log=$log_ad/ResultLog
raw_log=$log_ad/RawLog
machinecheck_log=$raw_log/MachineCheckLog
message_record_log=$machinecheck_log/MessagesRecord
system_log=$raw_log/SystemLog
machinecheck_dir=$(cd "$cur_dir/.." && pwd)/MachineCheck
file_dir=$cur_dir/Config_file
fio_result_dir=$result_log/fio_result
result_dir=$fio_result_dir
lib_dir=$cur_dir/lib
config_dir=$cur_dir/job_files
machine_dir=$machinecheck_dir
report_dir=$cur_dir/Report
record_dir=$log_ad/Record

# Legacy Camel_Dir aliases (external/old scripts may still use these).
CP_ROOT_DIR=$cp_root_dir
Cur_Dir=$cur_dir
Job_Dir=$job_dir
LogAd=$log_ad
TestErrorLog=$test_error_log
ResultLog=$result_log
RawLog=$raw_log
MachineCheckLog=$machinecheck_log
MessageRecordLog=$message_record_log
SystemLog=$system_log
MachineCheck_Dir=$machinecheck_dir
File_Dir=$file_dir
Fio_Result_Dir=$fio_result_dir
Result_Dir=$result_dir
Lib_Dir=$lib_dir
Config_Dir=$config_dir
Machine_Dir=$machine_dir
Report_Dir=$report_dir
Record_Dir=$record_dir
mce_log=/var/log/mcelog
messages_log=/var/log/messages
dmesg_log=/var/log/dmesg
#########################################find system########################################################

system_SLES11SP2=`[ -f /etc/issue ] && grep "SUSE Linux Enterprise Server 11 SP2" /etc/issue | wc -l || echo 0`
system_SLES11SP3=`[ -f /etc/issue ] && grep "SUSE Linux Enterprise Server 11 SP3" /etc/issue | wc -l || echo 0`
system_SLES12=`[ -f /etc/issue ] && grep "SUSE Linux Enterprise Server 12" /etc/issue | wc -l || echo 0`
system_Redhat5=`[ -f /etc/issue ] && grep "Red Hat Enterprise Linux Server release 5" /etc/issue | wc -l || echo 0`
system_Redhat6=`[ -f /etc/issue ] && grep "Red Hat Enterprise Linux Server release 6" /etc/issue | wc -l || echo 0`
system_Redhat7=`[ -f /etc/redhat-release ] && grep "release 7" /etc/redhat-release | wc -l || echo 0`
system_CentOS8=`[ -f /etc/redhat-release ] && grep "release 8" /etc/redhat-release | wc -l || echo 0`
system_CentOS6=`[ -f /etc/issue ] && grep "CentOS release 6" /etc/issue | wc -l || echo 0`
system_Ubuntu=`grep -i Ubuntu /proc/version 2>/dev/null | wc -l`
system_Debian=`[ -f /etc/issue ] && grep -i "Debian GNU" /etc/issue | wc -l || echo 0`
system_NFS=`[ -f /etc/issue ] && grep -i "NFS" /etc/issue | wc -l || echo 0`
system_NFS3=`[ -f /etc/os-release ] && grep -i "NFS Server 3" /etc/os-release | wc -l || echo 0`
System_Sugon=`[ -f /etc/os-release ] && grep "OEM-SUGON" /etc/os-release | wc -l || echo 0`
System_NFS_PC5=`[ -f /etc/os-release ] && grep "NFSDesktop" /etc/os-release | wc -l || echo 0`
system_kylin=`[ -f /etc/issue ] && grep -i kylin /etc/issue | wc -l || echo 0`
system_Kylin=`[ -f /etc/os-release ] && grep "kylin" /etc/os-release | wc -l || echo 0`
system_Kylin_Debian=`[ -f /etc/os-release ] && grep "debian" /etc/os-release | wc -l || echo 0`
system_Redhat9=`[ -f /etc/redhat-release ] && grep -E 'Red Hat Enterprise Linux release 9\.' /etc/redhat-release | wc -l || echo 0`
system_UOS_Server=`[ -f /etc/os-release ] && grep 'UnionTech OS Server 20' /etc/os-release | wc -l || echo 0`
system_ctyunos=`[ -f /etc/os-release ] && grep -i "NAME=\"ctyunos\"" /etc/os-release | wc -l || echo 0`
system_Rocky9=`[ -f /etc/os-release ] && grep "Rocky Linux 9" /etc/os-release | wc -l || echo 0`

#############################################################################################################
platform=`lscpu |grep -i 'model name'|awk -F':' '{print$2}'|sed  's/[[:space:]]//'|tr a-z A-Z`
####################
show_produce_message() {
    local i
    # Suppress tput errors in non-interactive shells (like Jenkins)
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
	# Remove ANSI color codes to prevent messy logs in Web UI
	echo -ne "$TEXT"
	echo
}
