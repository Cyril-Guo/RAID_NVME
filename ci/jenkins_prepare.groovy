def preparePhysicalIoDriver(Map cfg) {
    def script = cfg.script
    def env = cfg.env
    def params = cfg.params
    def selectedTestItems = cfg.selectedTestItems ?: []
    def jenkinsHome = cfg.jenkinsHome ?: (env.JENKINS_HOME ?: '/var/lib/jenkins')

    def state = [
        needsPhysicalIoDriverPrep: selectedTestItems.contains('env_prepare'),
        triggerSource: 'Manual Build',
        kernelDriverCommit: 'skipped',
        kernelDriverFullCommit: '',
        kernelDriverRef: '',
        kernelDriverMrIid: '',
        kernelDriverMrTitle: '',
        kernelDriverMrUpdatedAt: '',
        kernelDriverMrUrl: '',
        raidCliCommit: 'skipped',
        raidCliFullCommit: '',
        raidCliDpraidPath: '',
    ]

    script.echo "Selected test items: ${selectedTestItems}"
    script.echo "Pull latest raid_cli/kernel_driver for env_prepare: ${state.needsPhysicalIoDriverPrep}"

    if (!state.needsPhysicalIoDriverPrep) {
        script.echo 'Skip raid_cli sync and kernel_driver checkout: env_prepare not selected.'
        if ((params.MANUAL_MR_IID ?: '').trim() || (params.MANUAL_KERNEL_DRIVER_REF ?: '').trim()) {
            script.echo 'MANUAL_MR_IID / MANUAL_KERNEL_DRIVER_REF ignored because env_prepare is not selected.'
        }
        return state
    }

    // CI is manual-only: default kernel_driver/main; optional MANUAL_MR_IID or MANUAL_KERNEL_DRIVER_REF.
    def raidCliMarkerName = "${env.JOB_NAME}_${env.RAID_CLI_BRANCH}_raid_cli_commit".replaceAll('[^A-Za-z0-9_.-]', '_')
    def raidCliMarkerPath = "${jenkinsHome}/.raid_nvme/${raidCliMarkerName}.commit"
    def raidCliWorkDir = "${jenkinsHome}/.raid_nvme/${raidCliMarkerName}.repo"
    state.raidCliDpraidPath = "${raidCliWorkDir}/dpraid"
    def mrProps = [:]

    def syncRaidCli = { String reason ->
        script.echo "Check raid_cli(${env.RAID_CLI_BRANCH}) updates: ${reason}."
        script.checkout scm: [
            $class: 'GitSCM',
            branches: [[name: "*/${env.RAID_CLI_BRANCH}"]],
            userRemoteConfigs: [[
                url: env.RAID_CLI_REPO,
                credentialsId: env.RAID_CLI_CRED
            ]],
            extensions: [
                [$class: 'RelativeTargetDirectory', relativeTargetDir: 'raid_cli'],
                [$class: 'CloneOption', shallow: true, depth: 50, noTags: true, timeout: 30]
            ]
        ], poll: false, changelog: false

        state.raidCliFullCommit = script.sh(
            script: "git -C raid_cli rev-parse HEAD 2>/dev/null || echo unknown",
            returnStdout: true
        ).trim()
        state.raidCliCommit = script.sh(
            script: "git -C raid_cli rev-parse --short HEAD 2>/dev/null || echo unknown",
            returnStdout: true
        ).trim()

        def previousRaidCliCommit = script.sh(
            script: "cat '${raidCliMarkerPath}' 2>/dev/null || true",
            returnStdout: true
        ).trim()
        def persistentRaidCliMissing = script.sh(
            script: "test -d '${raidCliWorkDir}/.git' && test -x '${state.raidCliDpraidPath}'; echo \$?",
            returnStdout: true
        ).trim() != '0'
        def needsRaidCliUpdate = state.raidCliFullCommit != 'unknown' &&
            (previousRaidCliCommit != state.raidCliFullCommit || persistentRaidCliMissing)

        if (needsRaidCliUpdate) {
            script.sh """
            set -eu
            mkdir -p '${jenkinsHome}/.raid_nvme'
            rm -rf '${raidCliWorkDir}.next'
            cp -a raid_cli '${raidCliWorkDir}.next'
            rm -rf '${raidCliWorkDir}'
            mv '${raidCliWorkDir}.next' '${raidCliWorkDir}'
            cd '${raidCliWorkDir}'
            chmod +x ./build.sh
            ./build.sh
            test -x ./dpraid
            printf '%s\\n' '${state.raidCliFullCommit}' > '${raidCliMarkerPath}'
            """
            script.currentBuild.description = "raid_cli ${state.raidCliCommit}"
            script.echo "raid_cli(${env.RAID_CLI_BRANCH}) updated and built on Jenkins server: ${previousRaidCliCommit ?: 'none'} -> ${state.raidCliFullCommit}"
            script.echo "raid_cli checkout path: ${raidCliWorkDir}"
            script.echo "dpraid artifact path: ${state.raidCliDpraidPath}"
        } else {
            script.echo "raid_cli(${env.RAID_CLI_BRANCH}) has no new commit: ${state.raidCliCommit}"
        }

        return needsRaidCliUpdate
    }

    def manualMrIid = (params.MANUAL_MR_IID ?: '').trim()
    def manualKernelDriverRef = (params.MANUAL_KERNEL_DRIVER_REF ?: '').trim()
    syncRaidCli('env_prepare selected')

    if (manualMrIid) {
        if (manualKernelDriverRef) {
            script.echo "MANUAL_MR_IID is set; ignore MANUAL_KERNEL_DRIVER_REF=${manualKernelDriverRef}."
        }
        if (!(manualMrIid ==~ /^[0-9]+$/)) {
            script.error "MANUAL_MR_IID must be a numeric GitLab merge request IID, got: ${manualMrIid}"
        }

        script.withCredentials([string(credentialsId: env.KERNEL_DRIVER_GITLAB_TOKEN_CRED, variable: 'GITLAB_TOKEN')]) {
            script.sh """
            set -eu
            curl -fsS \\
              --header "PRIVATE-TOKEN: \${GITLAB_TOKEN}" \\
              "${env.KERNEL_DRIVER_GITLAB_API}/projects/${env.KERNEL_DRIVER_GITLAB_PROJECT}/merge_requests/${manualMrIid}" \\
              -o kernel_driver_manual_mr.json

            python3 ci/gitlab_mr_to_properties.py kernel_driver_manual_mr.json > kernel_driver_manual_mr.properties
            """
        }

        script.readFile('kernel_driver_manual_mr.properties').split('\\r?\\n').each { line ->
            if (line.contains('=')) {
                def parts = line.split('=', 2)
                mrProps[parts[0]] = parts[1]
            }
        }

        state.kernelDriverRef = mrProps.MR_SOURCE_BRANCH ?: env.KERNEL_DRIVER_BRANCH
        state.kernelDriverMrIid = mrProps.MR_IID ?: manualMrIid
        state.kernelDriverMrTitle = mrProps.MR_TITLE ?: ''
        state.kernelDriverMrUpdatedAt = mrProps.MR_UPDATED_AT ?: ''
        state.kernelDriverMrUrl = mrProps.MR_WEB_URL ?: ''
        state.triggerSource = 'Manual MR Build'
        script.echo "Manual MR build requested. Run tests on kernel_driver !${state.kernelDriverMrIid} ${state.kernelDriverRef}."
    } else {
        if (manualKernelDriverRef) {
            if (!(manualKernelDriverRef ==~ '[A-Za-z0-9][A-Za-z0-9._/-]*') ||
                manualKernelDriverRef.contains('..') ||
                manualKernelDriverRef.endsWith('/')) {
                script.error "MANUAL_KERNEL_DRIVER_REF is not a safe branch name: ${manualKernelDriverRef}"
            }
            state.kernelDriverRef = manualKernelDriverRef
            state.triggerSource = 'Manual Branch Build'
        } else {
            state.kernelDriverRef = env.KERNEL_DRIVER_BRANCH
            state.triggerSource = 'Manual Build'
        }
        script.echo "Manual build requested. Run tests on kernel_driver/${state.kernelDriverRef}."
    }

    script.checkout scm: [
        $class: 'GitSCM',
        branches: [[name: "*/${state.kernelDriverRef}"]],
        userRemoteConfigs: [[
            url: env.KERNEL_DRIVER_REPO,
            credentialsId: env.KERNEL_DRIVER_CRED
        ]],
        extensions: [
            [$class: 'RelativeTargetDirectory', relativeTargetDir: 'kernel_driver'],
            [$class: 'CloneOption', shallow: true, depth: 50, noTags: true, timeout: 30]
        ]
    ], poll: false, changelog: false

    def mrSha = mrProps.MR_SHA ?: ''
    if (mrSha ==~ /^[0-9a-f]{40}$/) {
        script.sh "git -C kernel_driver checkout --detach '${mrSha}'"
    }

    state.kernelDriverFullCommit = script.sh(
        script: "git -C kernel_driver rev-parse HEAD 2>/dev/null || echo unknown",
        returnStdout: true
    ).trim()
    state.kernelDriverCommit = script.sh(
        script: "git -C kernel_driver rev-parse --short HEAD 2>/dev/null || echo unknown",
        returnStdout: true
    ).trim()
    script.echo "kernel_driver(${state.kernelDriverRef}) commit: ${state.kernelDriverCommit}"

    // Stage dpraid into workspace so deploy packs it for per-case refresh only.
    script.sh """
    set -eu
    test -x '${state.raidCliDpraidPath}'
    mkdir -p artifacts
    install -m 0755 '${state.raidCliDpraidPath}' artifacts/dpraid
    """

    return state
}

return this
