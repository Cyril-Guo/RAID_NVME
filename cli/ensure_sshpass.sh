#!/usr/bin/env bash
set -euo pipefail

# Ensure sshpass exists on the Jenkins agent for password-based SSH/SCP.

if command -v sshpass >/dev/null 2>&1; then
    exit 0
fi

echo "sshpass is missing on Jenkins server, try to install it automatically."
if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get -o DPkg::Lock::Timeout=600 update
    sudo apt-get -o DPkg::Lock::Timeout=600 install -y sshpass
elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y sshpass
elif command -v yum >/dev/null 2>&1; then
    sudo yum install -y sshpass
elif command -v zypper >/dev/null 2>&1; then
    sudo zypper install -y sshpass
fi

command -v sshpass >/dev/null 2>&1 || {
    echo "sshpass is required on Jenkins server, and automatic install failed" >&2
    exit 1
}
