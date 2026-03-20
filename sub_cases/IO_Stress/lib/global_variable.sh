#!/bin/bash
export LANG=C.UTF-8
export LC_ALL=C.UTF-8
product_name=`dmidecode -t system|grep -i "Product Name"|awk -F ":" '{print $2}'|sed 's/ //g'|head -1` > /dev/null
if [[ $product_name == "" ]];then
   product_name="SUT"
fi

CP_ROOT_DIR=$(cd "$(dirname "$0")";pwd)
Cur_Dir=$(cd "$(dirname "$0")";pwd)
Job_Dir=$Cur_Dir/job_files
LogAd=$Cur_Dir/log
TestErrorLog=$LogAd/TestErrorLog
ResultLog=$LogAd/ResultLog
RawLog=$LogAd/RawLog
MachineCheckLog=$RawLog/MachineCheckLog
MessageRecordLog=$MachineCheckLog/MessagesRecord
SystemLog=$RawLog/SystemLog
MachineCheck_Dir=$Cur_Dir/MachineCheck
File_Dir=$Cur_Dir/Config_file
Fio_Result_Dir=$ResultLog/fio_result
Result_Dir=$Fio_Result_Dir

Lib_Dir=$Cur_Dir/lib
Config_Dir=$Cur_Dir/job_files

Machine_Dir=$MachineCheck_Dir
Report_Dir=$Cur_Dir/Report
Record_Dir=$LogAd/Record
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
system_Redhat9=`[ -f /etc/redhat-release ] && grep 'Red Hat Enterprise Linux release 9.0 ' /etc/redhat-release | wc -l || echo 0`
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
