#!/bin/bash
set -euo pipefail

: "${NODE_IP:?NODE_IP is required}"
: "${TARGET_USER:?TARGET_USER is required}"
: "${REMOTE_DIR:?REMOTE_DIR is required}"

SSH_OPTS=${SSH_OPTS:-}
TARGET_PASSWORD=${TARGET_PASSWORD:-123456}
export SSHPASS="${TARGET_PASSWORD}"
if [ -z "${REMOTE_SSH_COMMAND:-}" ]; then
    REMOTE_SSH_COMMAND="sshpass -e ssh ${SSH_OPTS} ${TARGET_USER}@${NODE_IP}"
fi

tar \
  --exclude='./.git' \
  --exclude='./kernel_driver/.git' \
  --exclude='./raid_cli' \
  --exclude='./.pytest_cache' \
  --exclude='./__pycache__' \
  --exclude='./allure-results' \
  --exclude='./report.xml' \
  --exclude='./report_*.xml' \
  --exclude='./test_execution_*.log' \
  --exclude='./environment_prepare_*.log' \
  --exclude='./feishu_payload.json' \
  -czf - . | eval "${REMOTE_SSH_COMMAND} 'tar -xzf - -C ${REMOTE_DIR}'"
