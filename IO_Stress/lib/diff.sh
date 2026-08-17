#!/bin/bash

IFS=$'\n'

# Compare only stable inventory fields. Ignore banners, tool versions, CPU summary, timestamps.
machinecheck_fingerprint() {
    local file="$1"
    sed 's/[[:space:]]\+/ /g; s/^ //; s/ $//' "$file" | awk '
        $1 == "disk:" || $1 == "pcie_nvme:" || $1 == "link:" || $1 == "aer:" { print; next }
        $1 == "disk" && $2 == "count:" { print; next }
        $1 == "pcie_nvme" && $2 == "count:" { print; next }
    ' | sort
}

# Human-readable whitelist diff: show only changed keys / AER flag bits / link attrs.
# Args: golden_fp current_fp
format_machinecheck_diff() {
    local golden="$1"
    local current="$2"
    awk -f - "$golden" "$current" <<'AWK'
function trim(s) {
    sub(/^[[:space:]]+/, "", s)
    sub(/[[:space:]]+$/, "", s)
    return s
}

function line_key(line,   n, a) {
    sub(/\r$/, "", line)
    n = split(line, a, /[[:space:]]+/)
    if (n < 1) return line
    if (a[1] == "aer:" || a[1] == "link:" || a[1] == "pcie_nvme:" || a[1] == "disk:")
        return a[1] " " a[2]
    if (a[1] == "disk" && a[2] == "count:")
        return "disk count:"
    if (a[1] == "pcie_nvme" && a[2] == "count:")
        return "pcie_nvme count:"
    return line
}

function line_payload(line, key,   p) {
    p = line
    if (index(p, key) == 1)
        p = substr(p, length(key) + 1)
    return trim(p)
}

function clear_map(m,   k) {
    for (k in m) delete m[k]
}

# AER: "UESta=DLP- SDES- ... CESta=RxErr- ... AdvNonFatalErr+" -> flag -> polarity
function parse_aer_flags(payload, out,   n, a, i, tok, name, pol, section) {
    clear_map(out)
    n = split(payload, a, /[[:space:]]+/)
    section = ""
    for (i = 1; i <= n; i++) {
        tok = a[i]
        if (tok ~ /^UESta=/) {
            section = "UESta"
            sub(/^UESta=/, "", tok)
        } else if (tok ~ /^CESta=/) {
            section = "CESta"
            sub(/^CESta=/, "", tok)
        }
        if (tok ~ /[+-]$/) {
            pol = substr(tok, length(tok), 1)
            name = substr(tok, 1, length(tok) - 1)
            if (name != "") {
                if (section != "")
                    out[section "." name] = pol
                else
                    out[name] = pol
            }
        }
    }
}

# link / generic KEY=VALUE tokens
function parse_kv(payload, out,   n, a, i, eq, k, v) {
    clear_map(out)
    n = split(payload, a, /[[:space:]]+/)
    for (i = 1; i <= n; i++) {
        eq = index(a[i], "=")
        if (eq > 1) {
            k = substr(a[i], 1, eq - 1)
            v = substr(a[i], eq + 1)
            out[k] = v
        }
    }
}

function print_map_diff(gmap, cmap,   k, nchg, keys, kn, i, j, t) {
    nchg = 0
    for (k in gmap) if (!(k in cmap) || gmap[k] != cmap[k]) nchg++
    for (k in cmap) if (!(k in gmap)) nchg++
    if (nchg == 0) {
        print "  (payload text differs; no parseable flag/attr pairs)"
        return
    }
    kn = 0
    for (k in gmap) keys[++kn] = k
    for (k in cmap) if (!(k in gmap)) keys[++kn] = k
    for (i = 2; i <= kn; i++) {
        t = keys[i]
        j = i - 1
        while (j >= 1 && keys[j] > t) {
            keys[j + 1] = keys[j]
            j--
        }
        keys[j + 1] = t
    }
    for (i = 1; i <= kn; i++) {
        k = keys[i]
        if (k in gmap && k in cmap) {
            if (gmap[k] != cmap[k])
                print "  " k ": " gmap[k] " -> " cmap[k]
        } else if (k in gmap) {
            print "  " k ": " gmap[k] " -> (missing)"
        } else {
            print "  " k ": (missing) -> " cmap[k]
        }
    }
}

BEGIN {
    # ARGV[1]=golden ARGV[2]=current; read manually
}

FNR == NR {
    sub(/\r$/, "", $0)
    gkey = line_key($0)
    golden[gkey] = $0
    gorder[++gn] = gkey
    next
}

{
    sub(/\r$/, "", $0)
    ckey = line_key($0)
    current[ckey] = $0
    corder[++cn] = ckey
}

END {
    changed = 0
    only_g = 0
    only_c = 0

    print "Changed fields (Golden -> Current):"
    print ""

    for (i = 1; i <= gn; i++) {
        k = gorder[i]
        if (!(k in seen_g)) {
            seen_g[k] = 1
            glist[++glistn] = k
        }
    }
    for (i = 1; i <= cn; i++) {
        k = corder[i]
        if (!(k in seen_c)) {
            seen_c[k] = 1
            clist[++clistn] = k
        }
    }

    for (i = 1; i <= glistn; i++) {
        k = glist[i]
        if (!(k in current)) {
            only_g++
            print "[ONLY GOLDEN] " golden[k]
            print ""
            continue
        }
        if (golden[k] == current[k]) continue
        changed++
        print "[" k "]"
        gp = line_payload(golden[k], k)
        cp = line_payload(current[k], k)
        if (k ~ /^aer:/) {
            parse_aer_flags(gp, gflags)
            parse_aer_flags(cp, cflags)
            print_map_diff(gflags, cflags)
        } else if (k ~ /^link:/) {
            parse_kv(gp, gflags)
            parse_kv(cp, cflags)
            print_map_diff(gflags, cflags)
        } else if (k == "disk count:" || k == "pcie_nvme count:") {
            print "  " gp " -> " cp
        } else if (k ~ /^pcie_nvme:/) {
            parse_kv(gp, gflags)
            parse_kv(cp, cflags)
            # desc-only lines may have no kv; fall back
            nkv = 0
            for (x in gflags) nkv++
            for (x in cflags) nkv++
            if (nkv > 0)
                print_map_diff(gflags, cflags)
            else {
                print "  golden : " gp
                print "  current: " cp
            }
        } else {
            print "  golden : " gp
            print "  current: " cp
        }
        print ""
    }

    for (i = 1; i <= clistn; i++) {
        k = clist[i]
        if (!(k in golden)) {
            only_c++
            print "[ONLY CURRENT] " current[k]
            print ""
        }
    }

    print "Summary: " changed " changed, " only_g " only-in-golden, " only_c " only-in-current"
}
AWK
}

function record_errorinfo(){
    local fp_before fp_after formatted
    fp_before=$(mktemp)
    fp_after=$(mktemp)
    formatted=$(mktemp)
    machinecheck_fingerprint "$MachineCheckLog/info_before.log" > "$fp_before"
    machinecheck_fingerprint "$MachineCheckLog/info_after.log" > "$fp_after"
    format_machinecheck_diff "$fp_before" "$fp_after" > "$formatted"

    {
        echo "ERROR: MachineCheck Log Inconsistency Detected!"
        echo "=================================================="
        echo "Current Loop: $loop"
        echo "Time: $(date)"
        cat "$formatted"
        echo "--------------------------------------------------"
    } | tee -a "$TestErrorLog/machine_diff_error.log" "$Result_Dir/result.log"

    echo -e " ERROR: MachineCheck inconsistencies found at loop $loop. Check $TestErrorLog/machine_diff_error.log for details." | tee -a "$Result_Dir/result.log"

    # Also record to diff_all.log
    {
        echo -e "\n--- Loop $loop Error Record ---"
        cat "$formatted"
    } >> "$MessageRecordLog/diff_all.log"
    rm -f "$fp_before" "$fp_after" "$formatted"
}

function diff_messages()
{
    if [[ $check == "NO" ]];then
        echo "no check,exit"
        echo "diff finish" >$LogAd/diff.flag
        return 1
    else
        show_produce_message "Computed FIO deviation"
        if [[ -n "$loop" && "$loop" != "0" ]];then
            date +%Y-%m-%d_%H:%M:%S | tee -a $Fio_Result_Dir/result_fio.log
            if [[ -f $Fio_Result_Dir/result_0.csv && -f $Fio_Result_Dir/result_${loop}.csv ]]; then
                fio_mode_list=($(cat $Fio_Result_Dir/result_0.csv 2>/dev/null | sed -n '2,$p' | awk '{print $1}'))
                for fio_mode in ${fio_mode_list[*]};do
                    if [[ ! $fio_mode ]];then continue; fi
                    before_iops=$(cat $Fio_Result_Dir/result_0.csv 2>/dev/null | grep "^$fio_mode" | awk '{print $7}' | awk -F, '{print $1}')
                    after_iops=$(cat $Fio_Result_Dir/result_${loop}.csv 2>/dev/null | grep "^$fio_mode" | awk '{print $7}' | awk -F, '{print $1}')
                    
                    # Ensure values are numbers before processing
                    [[ -z "$before_iops" || -z "$after_iops" ]] && continue

                    # ... (Handle 'k' in IOPS as before) ...
                    if [[ $before_iops =~ k ]]; then before_iops=$(echo "$before_iops" | awk -Fk '{print $1}' | awk '{print $1*1000}'); fi
                    if [[ $after_iops =~ k ]]; then after_iops=$(echo "$after_iops" | awk -Fk '{print $1}' | awk '{print $1*1000}'); fi
                    
                    before_bw=$(cat $Fio_Result_Dir/result_0.csv 2>/dev/null | grep "^$fio_mode" | awk '{print $11}' | awk -FM '{print $1}')
                    after_bw=$(cat $Fio_Result_Dir/result_${loop}.csv 2>/dev/null | grep "^$fio_mode" | awk '{print $11}' | awk -FM '{print $1}')
                    
                    [[ -z "$before_bw" || -z "$after_bw" ]] && continue

                    echo "$fio_mode" | tee -a $Fio_Result_Dir/result_fio.log
                    echo "Before Value: IOPS $before_iops, BW $before_bw" | tee -a $Fio_Result_Dir/result_fio.log
                    echo "After Value: IOPS $after_iops, BW $after_bw" | tee -a $Fio_Result_Dir/result_fio.log
                    
                    deviation_iops=$(echo "scale=2; if($after_iops > $before_iops) ($after_iops-$before_iops)/$before_iops*100 else ($before_iops-$after_iops)/$before_iops*100" | bc 2>/dev/null)
                    deviation_bw=$(echo "scale=2; if($after_bw > $before_bw) ($after_bw-$before_bw)/$before_bw*100 else ($before_bw-$after_bw)/$before_bw*100" | bc 2>/dev/null)
                    echo "Deviation: IOPS ${deviation_iops-0}%, BW ${deviation_bw-0}%" | tee -a $Fio_Result_Dir/result_fio.log
                done
            else
                echo "Wait for first complete loop to show performance deviation..."
            fi
        fi
        
        cd $MachineCheck_Dir >/dev/null
        show_produce_message "Start MachineCheck"
        bash MachineCheck.sh

        # compare_log
        if [[ -f $MachineCheck_Dir/Result/machinecheck.log ]]; then
            process_machinecheck_results "$MachineCheckLog/info_after.log"
        else
            echo "Warning: MachineCheck.sh did not produce machinecheck.log" | tee -a $Result_Dir/result.log
        fi

        if [[ -f $MachineCheckLog/info_after.log ]]; then
            echo "Machinecheck finish" >> $MachineCheckLog/info_after.log
            cp -f $MachineCheckLog/info_after.log $MachineCheckLog/${loop}_machinecheck.log
        fi
        
        # Whitelist field differences (disk/pcie_nvme/link/aer + counts)
        if [[ ! -f $MachineCheckLog/info_before.log ]] || [[ ! -f $MachineCheckLog/info_after.log ]]; then
            echo "ERROR: Missing log files for MachineCheck diff comparison." | tee -a $Result_Dir/result.log
            echo "diff finish" >$LogAd/diff.flag
            return 3
        fi
        local fp_before fp_after
        fp_before=$(mktemp)
        fp_after=$(mktemp)
        machinecheck_fingerprint "$MachineCheckLog/info_before.log" > "$fp_before"
        machinecheck_fingerprint "$MachineCheckLog/info_after.log" > "$fp_after"
        if ! diff -q "$fp_before" "$fp_after" > /dev/null; then
            echo "Whitelist field differences detected between MachineCheck before/after logs." | tee -a $Result_Dir/result.log
            rm -f "$fp_before" "$fp_after"
            record_errorinfo
            echo "diff finish" >$LogAd/diff.flag
            return 3
        fi
        rm -f "$fp_before" "$fp_after"
    fi
    echo "diff finish" >$LogAd/diff.flag
    return 1
}



########################################################################################################
function info_diff()
{
    sleep 30




    diff_messages
    if [ $? -eq 3 ]; then
        if [ $flag == "STOP" ];then
            echo "stop_flag is STOP,so exit"
            collect_log
            test_end 3
        elif [ "$flag" == "NON-STOP" ];then
            echo "stop_flag is NON-STOP, ignore error and continue..."
            return 0
        else
            echo "Unsupport stop flag, and it shoule be STOP or NON-STOP, exit..."
            exit 2
        fi
    fi
}  
