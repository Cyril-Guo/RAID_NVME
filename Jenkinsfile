def targetIPs = []
def shouldRunTests = false

def hostSshCmd(ip) {
    return "SSHPASS='${env.TARGET_PASSWORD}' sshpass -e ssh ${env.SSH_OPTS} ${env.TARGET_USER}@${ip}"
}

def hostScpCmd() {
    return "SSHPASS='${env.TARGET_PASSWORD}' sshpass -e scp ${env.SSH_OPTS}"
}

def sanitizePathSegment(value) {
    def text = (value ?: 'unknown').toString().trim()
    text = text.replaceAll('^origin/', '')
    text = text.replaceAll('[^A-Za-z0-9._-]', '_')
    if (!text) {
        text = 'unknown'
    }
    return text
}

def resolveRaidNvmeBranch() {
    def branch = (
        env.BRANCH_NAME ?: env.GIT_BRANCH ?: env.CHANGE_BRANCH ?: ''
    ).toString().trim().replaceAll('^origin/', '')

    if (!branch || branch == 'HEAD') {
        try {
            def scmBranch = scm?.branches ? scm.branches[0]?.name?.toString() : ''
            branch = (scmBranch ?: '')
                .replaceAll('^\\*/', '')
                .replaceAll('^origin/', '')
                .trim()
        } catch (Exception ignored) {
            branch = ''
        }
    }

    if (!branch || branch == 'HEAD') {
        branch = sh(
            script: '''
set +e
b=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
if [ -n "$b" ] && [ "$b" != "HEAD" ]; then printf '%s\\n' "$b"; exit 0; fi
printf '\\n'
''',
            returnStdout: true
        ).trim()
    }

    if (!branch || branch == 'HEAD') {
        branch = (env.JOB_BASE_NAME ?: env.JOB_NAME ?: 'CLI').toString().trim()
    }
    return branch
}

def dutLockName(ip) {
    return "raid-nvme-dut-${ip}"
}

def remoteWorkspaceRoot(kind) {
    def job = sanitizePathSegment(env.JOB_BASE_NAME ?: env.JOB_NAME ?: 'CLI')
    def branch = sanitizePathSegment(resolveRaidNvmeBranch())
    def build = sanitizePathSegment(env.BUILD_NUMBER ?: '0')
    return "/root/Cyril/Jenkins/${job}/${branch}/${kind}-${build}"
}

def copyWorkspaceToRemote(ip, remoteDir, targetUser, sshOpts) {
    sh """
chmod +x cli/deploy_workspace.sh
NODE_IP='${ip}' TARGET_USER='${targetUser}' SSH_OPTS='${sshOpts}' \\
TARGET_PASSWORD='${env.TARGET_PASSWORD}' REMOTE_DIR='${remoteDir}' \\
cli/deploy_workspace.sh
"""
}

pipeline {
    agent any

    options {
        skipDefaultCheckout()
    }

    parameters {
        booleanParam(
            name: 'RESTORE',
            defaultValue: false,
            description: 'Only stop running CLI test processes on target nodes. Do not run tests.'
        )
        text(
            name: 'TARGET_IPS',
            defaultValue: '192.168.22.134',
            description: 'Target node IPv4 addresses, one per line. Blank lines and lines beginning with # are ignored.'
        )
        string(
            name: 'TARGET_PASSWORD',
            defaultValue: '123456',
            trim: true,
            description: 'Physical host SSH password for TARGET_USER (default 123456).'
        )
    }

    environment {
        TARGET_USER = 'root'
        TARGET_PASSWORD = "${params.TARGET_PASSWORD?.trim() ?: '123456'}"
        SSH_OPTS = '-o StrictHostKeyChecking=no -o PreferredAuthentications=password -o PubkeyAuthentication=no -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ConnectTimeout=15'
    }

    stages {
        stage('Prepare Workspace') {
            steps {
                cleanWs()
                checkout scm: scm, poll: false, changelog: false
                sh 'chmod +x cli/*.sh'

                script {
                    echo "Jenkins node=${env.NODE_NAME}. Branch=${resolveRaidNvmeBranch()}."
                    shouldRunTests = !params.RESTORE

                    def ipContent = (params.TARGET_IPS ?: '').trim()
                    targetIPs = ipContent.split('\\r?\\n')
                        .collect { it.trim() }
                        .findAll { it != '' && !it.startsWith('#') }
                        .unique()

                    if (targetIPs.size() == 0) {
                        error 'No valid target IPs provided in TARGET_IPS.'
                    }

                    def invalidIPs = targetIPs.findAll { candidate ->
                        def octets = candidate.tokenize('.')
                        octets.size() != 4 || octets.any { octet ->
                            !(octet ==~ /^\d{1,3}$/) || octet.toInteger() > 255
                        }
                    }
                    if (invalidIPs.size() > 0) {
                        error "Invalid TARGET_IPS entries: ${invalidIPs.join(', ')}."
                    }
                    echo "Target nodes: ${targetIPs}"
                }
            }
        }

        stage('Restore Targets') {
            when { expression { return params.RESTORE } }
            steps {
                script {
                    def restoreTasks = [:]
                    for (int i = 0; i < targetIPs.size(); i++) {
                        def ip = targetIPs[i]
                        restoreTasks["Restore_${ip}"] = {
                            lock(resource: dutLockName(ip)) {
                                stage("Restore on ${ip}") {
                                    def restoreSsh = hostSshCmd(ip)
                                    echo "[${ip}] stop CLI test processes"
                                    sh """
                                    ${restoreSsh} '
                                        pkill -9 -f nvme_raid_test.py 2>/dev/null || true
                                        pkill -9 -f pytest 2>/dev/null || true
                                    ' || true
                                    """
                                }
                            }
                        }
                    }
                    parallel restoreTasks
                }
            }
        }

        stage('Run Tests') {
            when { expression { return shouldRunTests } }
            steps {
                script {
                    def parallelTasks = [:]
                    for (int i = 0; i < targetIPs.size(); i++) {
                        def ip = targetIPs[i]
                        parallelTasks["Node_${ip}"] = {
                            lock(resource: dutLockName(ip)) {
                                stage("Test on ${ip}") {
                                    def remoteDir = remoteWorkspaceRoot('build')
                                    def targetSsh = hostSshCmd(ip)
                                    def targetScp = hostScpCmd()

                                    echo "[${ip}] remote workspace: ${remoteDir}"
                                    sh "${targetSsh} 'rm -rf ${remoteDir} && mkdir -p ${remoteDir}'"
                                    copyWorkspaceToRemote(ip, remoteDir, env.TARGET_USER, env.SSH_OPTS)

                                    def testStatus = sh(
                                        returnStatus: true,
                                        script: """#!/bin/bash
set -euo pipefail
chmod +x cli/run_remote_test_and_collect.sh
NODE_IP='${ip}' \\
TARGET_USER='${env.TARGET_USER}' \\
REMOTE_DIR='${remoteDir}' \\
REMOTE_SSH_COMMAND="${targetSsh}" \\
REMOTE_SCP_COMMAND="${targetScp}" \\
cli/run_remote_test_and_collect.sh
"""
                                    )
                                    junit allowEmptyResults: true, testResults: "node-report_${ip}.xml"
                                    archiveArtifacts artifacts: "test_execution_${ip}.log,node-report_${ip}.xml", allowEmptyArchive: true
                                    if (testStatus != 0) {
                                        error "[${ip}] CLI tests failed with exit code ${testStatus}"
                                    }
                                }
                            }
                        }
                    }
                    parallel parallelTasks
                }
            }
        }
    }
}
