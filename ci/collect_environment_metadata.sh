#!/bin/bash
set -euo pipefail

: "${NODE_IP:?NODE_IP is required}"
: "${REMOTE_DIR:?REMOTE_DIR is required}"

PREFIX=${PREFIX:-Node_${NODE_IP}}

cd "${REMOTE_DIR}"
mkdir -p allure-results
{
    echo "${PREFIX}_Host=$(hostname)"
    echo "${PREFIX}_Kernel=$(uname -r)"
    echo "${PREFIX}_NVMe_Count=$(ls /dev/nvme*n1 2>/dev/null | wc -l)"
} > "allure-results/environment_${NODE_IP}${SUFFIX:-}.properties"
