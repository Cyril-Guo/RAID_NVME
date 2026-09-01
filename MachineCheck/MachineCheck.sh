#!/bin/bash
export LANG=C.UTF-8
export LC_ALL=C.UTF-8
export TERM=linux
Cur_Dir=$(cd "$(dirname "$0")" && pwd)
Result_Dir="$Cur_Dir/Result"
pcie_timeout_seconds="${MACHINECHECK_PCIE_TIMEOUT_SECONDS:-15}"

rm -rf "$Result_Dir"
rm -rf "$Cur_Dir"/*.log
rm -rf "$Cur_Dir"/*.txt
mkdir -p "$Result_Dir"

###########################################common function###################################################
show_produce_message() {
        local i
        tput bold >/dev/null 2>&1
        TEXT=$1
        length_text=${#TEXT}
        let length_title=80-length_text
        let half=length_title/2
        local str=""
        for ((i = 0; i < half; i++)); do
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
    if [[ -f /etc/os-release ]]; then
        # shellcheck disable=SC1091
        source /etc/os-release
    fi
    if ! command -v nvme >/dev/null 2>&1; then
        case "${ID:-}" in
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
    if ! command -v lspci >/dev/null 2>&1; then
        case "${ID:-}" in
            ubuntu|debian)
                apt-get update >/dev/null
                apt-get install -y pciutils >/dev/null
                ;;
            centos|rocky|rhel|fedora)
                yum install -y pciutils >/dev/null || dnf install -y pciutils >/dev/null
                ;;
            *)
                echo "Unsupported OS for automatic online installation. Please install pciutils manually."
                ;;
        esac
    fi
    sleep 2
}

###########################################function tool ver###################################################
machine_info_check_tool_ver() {
        show_produce_message "Machine Information Checking tool version"
        show_item "MachineCheck Information"
        show_title "Tool Version"
        show_item "nvme" "$(nvme --version 2>/dev/null)"
        show_item "lspci" "$(lspci --version 2>/dev/null | head -n1)"
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

########################################### disk / PCIe / AER ###################################################

list_block_disks() {
    # Disk names only (TYPE=disk), sorted for stable before/after diff.
    lsblk -dn -o NAME,TYPE 2>/dev/null | awk '$2=="disk"{print $1}' | sort
}

list_nvme_pcie_controllers() {
    # Full domain:BDF + device description, sorted.
    lspci -Dnn 2>/dev/null | awk -F' ' '
        tolower($0) ~ /non-volatile memory controller/ {
            bdf=$1
            $1=""
            sub(/^ /, "")
            print bdf "\t" $0
        }
    ' | sort
}

extract_link_field() {
    # $1=lspci -vvv text, $2=LnkCap|LnkSta, $3=Speed|Width
    local text="$1"
    local section="$2"
    local field="$3"
    echo "$text" | awk -v section="$section" -v field="$field" '
        $0 ~ ("^[[:space:]]*" section ":") {
            if (match($0, field "[[:space:]]+[^,]+")) {
                value=substr($0, RSTART, RLENGTH)
                sub("^" field "[[:space:]]+", "", value)
                sub(/[[:space:]]*\(.*\)$/, "", value)
                print value
                exit
            }
        }
    '
}

extract_aer_field() {
    # $1=lspci -vvv text, $2=UESta|CESta -> raw flag tokens after the section label
    local text="$1"
    local section="$2"
    echo "$text" | awk -v section="$section" '
        $0 ~ ("^[[:space:]]*" section ":") {
            line=$0
            sub("^[[:space:]]*" section ":[[:space:]]*", "", line)
            gsub(/[[:space:]]+/, " ", line)
            gsub(/^ | $/, "", line)
            print line
            exit
        }
    '
}

check_block_disks() {
    show_produce_message "Block Disk Check (lsblk)"
    show_title "Disk Inventory"
    local count=0
    local name
    while read -r name; do
        [[ -z "$name" ]] && continue
        show_item "disk:" "$name"
        count=$((count + 1))
    done < <(list_block_disks)
    show_item "disk count:" "$count"
    show_produce_message "Block Disk Check (lsblk)"
}

check_nvme_pcie_devices() {
    show_produce_message "NVMe PCIe Device Check (lspci)"
    show_title "Non-Volatile Memory Controllers"
    local count=0
    local bdf desc
    while IFS=$'\t' read -r bdf desc; do
        [[ -z "$bdf" ]] && continue
        show_item "pcie_nvme:" "${bdf} ${desc}"
        count=$((count + 1))
    done < <(list_nvme_pcie_controllers)
    show_item "pcie_nvme count:" "$count"
    show_produce_message "NVMe PCIe Device Check (lspci)"
}

check_nvme_link_and_aer() {
    # Record-only snapshot. Per-loop MachineCheck before/after diff decides ERROR.
    show_produce_message "NVMe Link / AER Record"
    show_title "Link Speed Width and AER"
    local bdf desc detail cap_speed cap_width sta_speed sta_width ue_raw ce_raw probe_rc
    local probe_failed=0
    while IFS=$'\t' read -r bdf desc; do
        [[ -z "$bdf" ]] && continue
        echo "[MACHINECHECK] probe start bdf=${bdf} command=lspci-vvv timeout=${pcie_timeout_seconds}s" >&2
        detail=""
        probe_rc=0
        detail=$(timeout --kill-after=2s "${pcie_timeout_seconds}s" lspci -s "$bdf" -vvv 2>/dev/null) || probe_rc=$?
        if [[ $probe_rc -eq 124 || $probe_rc -eq 137 ]]; then
            echo "[MACHINECHECK] probe timeout bdf=${bdf} command=lspci-vvv rc=${probe_rc}" >&2
            show_item "link:" "${bdf} LnkCap_Speed=NA LnkCap_Width=NA LnkSta_Speed=NA LnkSta_Width=NA"
            show_item "aer:" "${bdf} UESta=NA CESta=NA"
            probe_failed=1
            continue
        fi
        echo "[MACHINECHECK] probe finish bdf=${bdf} command=lspci-vvv rc=${probe_rc}" >&2
        if [[ -z "$detail" ]]; then
            show_item "link:" "${bdf} LnkCap_Speed=NA LnkCap_Width=NA LnkSta_Speed=NA LnkSta_Width=NA"
            show_item "aer:" "${bdf} UESta=NA CESta=NA"
            continue
        fi

        cap_speed=$(extract_link_field "$detail" "LnkCap" "Speed")
        cap_width=$(extract_link_field "$detail" "LnkCap" "Width")
        sta_speed=$(extract_link_field "$detail" "LnkSta" "Speed")
        sta_width=$(extract_link_field "$detail" "LnkSta" "Width")
        show_item "link:" "${bdf} LnkCap_Speed=${cap_speed:-NA} LnkCap_Width=${cap_width:-NA} LnkSta_Speed=${sta_speed:-NA} LnkSta_Width=${sta_width:-NA}"

        ue_raw=$(extract_aer_field "$detail" "UESta")
        ce_raw=$(extract_aer_field "$detail" "CESta")
        show_item "aer:" "${bdf} UESta=${ue_raw:-NA} CESta=${ce_raw:-NA}"
    done < <(list_nvme_pcie_controllers)
    show_produce_message "NVMe Link / AER Record"
    if [[ $probe_failed -ne 0 ]]; then
        return 124
    fi
}

# Execution
if [[ ! -f $Cur_Dir/install_flag ]]; then
    echo "First time run: ensuring tools are available."
    install_systemtools
    echo "done" > "$Cur_Dir/install_flag"
fi

machine_info_check_tool_ver >> "$Result_Dir/machinecheck.log"
machine_summary >> "$Result_Dir/machinecheck.log"
check_block_disks >> "$Result_Dir/machinecheck.log"
check_nvme_pcie_devices >> "$Result_Dir/machinecheck.log"
machinecheck_rc=0
check_nvme_link_and_aer >> "$Result_Dir/machinecheck.log" || machinecheck_rc=$?

cat "$Result_Dir/machinecheck.log"
exit "$machinecheck_rc"
