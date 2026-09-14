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

eval "${REMOTE_SSH_COMMAND} 'mkdir -p ${REMOTE_DIR}'"

tar \
  --exclude='./.git' \
  --exclude='./.pytest_cache' \
  --exclude='./__pycache__' \
  --exclude='./allure-results' \
  --exclude='./reports' \
  --exclude='./report.xml' \
  --exclude='./report_*.xml' \
  --exclude='./node-report*.xml' \
  --exclude='./test_execution_*.log' \
  -czf - . | eval "${REMOTE_SSH_COMMAND} 'tar -xzf - -C ${REMOTE_DIR}'"
