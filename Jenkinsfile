// 全局变量：存储从 target_ips.txt 读取的 IP 列表
def targetIPs = []
// 全局变量：本次触发对应的 kernel_driver 提交号（用于报告展示）
def kernelDriverCommit = ''

pipeline {
    agent any

    // 自动触发：每 15 分钟轮询 kernel_driver 的 main 分支，一旦有新提交即触发本冒烟测试。
    // 说明：轮询仅针对 kernel_driver（见准备阶段 checkout 的 poll:true）；RAID_NVME 测试
    //       框架自身的 checkout 设为 poll:false，因此对框架的推送不会误触发破坏性测试。
    triggers {
        pollSCM('H/15 * * * *')
    }

    // SMOKE 分支：测试项及全局配置(循环次数/是否忽略错误/指定磁盘/监控等)全部在
    // 仓库根目录的 test_items.txt 中维护，随代码一起部署到被测节点。
    //
    // 唯一保留的图形化选项：RESTORE(停止并清理)。勾选后本次构建不执行测试，
    // 仅对所有目标节点强制停止正在运行的测试(含后台 FIO / 监控进程)并恢复系统环境，
    // 方便随时中止测试。
    parameters {
        booleanParam(
            name: 'RESTORE',
            defaultValue: false,
            description: '仅停止并清理：立即停止所有目标节点上正在运行的测试(含后台 FIO / 监控进程)并恢复系统环境，本次构建不执行测试。'
        )
    }

    environment {
        // 飞书机器人 Webhook 地址
        FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/17fe4cfd-5e49-4ceb-b8c4-f002d74340ee'
        // 远程登录用户名
        TARGET_USER = 'root' 
        // 解锁破坏性写入测试开关 (1=允许)
        ALLOW_DESTRUCTIVE_FIO = '1'

        // ===== kernel_driver 源码仓库（被测对象）=====
        // main 分支有新提交时自动触发本冒烟测试
        KERNEL_DRIVER_REPO   = 'git@192.168.21.185:raid_max/kernel_driver.git'
        KERNEL_DRIVER_BRANCH = 'main'
        // Jenkins 凭据 ID：访问 192.168.21.185 的 SSH 私钥（需在 Jenkins 中预先创建，见 README）
        KERNEL_DRIVER_CRED   = 'kernel_driver_ssh'
    }

    stages {
        stage('准备阶段：拉取代码与读取 IP') {
            steps {
                cleanWs()

                // RAID_NVME 测试框架：poll:false —— 不参与轮询，其推送不会触发本任务
                checkout scm: scm, poll: false, changelog: true

                // kernel_driver：poll:true —— 参与轮询，main 分支有提交即触发；浅克隆到子目录
                script {
                    if (!params.RESTORE) {
                        checkout scm: [
                            $class: 'GitSCM',
                            branches: [[name: "*/${env.KERNEL_DRIVER_BRANCH}"]],
                            userRemoteConfigs: [[
                                url: env.KERNEL_DRIVER_REPO,
                                credentialsId: env.KERNEL_DRIVER_CRED
                            ]],
                            extensions: [
                                [$class: 'RelativeTargetDirectory', relativeTargetDir: 'kernel_driver'],
                                [$class: 'CloneOption', shallow: true, depth: 1, noTags: true, timeout: 30]
                            ]
                        ], poll: true, changelog: true

                        kernelDriverCommit = sh(
                            script: "git -C kernel_driver rev-parse --short HEAD 2>/dev/null || echo unknown",
                            returnStdout: true
                        ).trim()
                        echo "被测 kernel_driver(${env.KERNEL_DRIVER_BRANCH}) 当前提交: ${kernelDriverCommit}"
                    }
                }

                script {
                    if (fileExists('target_ips.txt')) {
                        def ipContent = readFile('target_ips.txt').trim()
                        targetIPs = ipContent.split('\\r?\\n').findAll { it.trim() != '' && !it.startsWith('#') }
                        
                        if (targetIPs.size() == 0) {
                            error "target_ips.txt 中未发现有效 IP 地址！"
                        }
                        echo "准备对以下节点执行并发测试: ${targetIPs}"
                    } else {
                        error "根目录下缺少 target_ips.txt 文件！"
                    }
                }
            }
        }

        stage('构建与安装 kernel_driver（占位，待补充）') {
            when { expression { return !params.RESTORE } }
            steps {
                script {
                    echo "被测驱动 kernel_driver 提交: ${kernelDriverCommit ?: '未知'}"
                    echo "【占位】此阶段用于把本次提交的 kernel_driver 部署到各被测节点并编译、安装/加载驱动。"
                    echo "【占位】构建方式待定（内核模块 .ko / 构建脚本 / 整棵内核），确定后在此实现真正的编译安装逻辑。"
                    // TODO(kernel_driver 构建与安装):
                    //   1) 将 kernel_driver 源码部署到各节点（当前已浅克隆在工作区 kernel_driver/ 目录）
                    //   2) 在节点上编译驱动
                    //   3) 安装并加载驱动（insmod/modprobe 或 make install）；失败应中止后续冒烟
                }
            }
        }

        stage('停止与清理：集群并发 Restore') {
            when { expression { return params.RESTORE } }
            steps {
                script {
                    def restoreTasks = [:]

                    for (int i = 0; i < targetIPs.size(); i++) {
                        def ip = targetIPs[i]

                        restoreTasks["Restore_${ip}"] = {
                            stage("Restore on ${ip}") {
                                // 独立临时目录，仅用于本次清理，结束后删除
                                def remoteDir = "/root/Cyril/Jenkins/jenkins_nvme_restore_${env.BUILD_NUMBER}"

                                echo "[${ip}] 1. 立即强制停止正在运行的测试进程(含后台)..."
                                // 先直接 pkill，确保即使部署/脚本异常也能第一时间停住测试
                                sh """
                                ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} '
                                    pkill -9 -f nvme_raid_test.py 2>/dev/null || true
                                    pkill -2 -f Stress_Monitor/main.py 2>/dev/null || true
                                    pkill -9 -f run_fio.sh 2>/dev/null || true
                                    pkill -9 -f Fio_All.sh 2>/dev/null || true
                                    pkill -9 fio 2>/dev/null || true
                                ' || true
                                """

                                echo "[${ip}] 2. 部署清理脚本..."
                                sh "ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} 'rm -rf ${remoteDir} && mkdir -p ${remoteDir}'"
                                // 排除 kernel_driver 源码大目录，避免把整棵内核树传到节点
                                sh "scp -o StrictHostKeyChecking=no -r \$(ls | grep -vx kernel_driver) ${env.TARGET_USER}@${ip}:${remoteDir}/"

                                echo "[${ip}] 3. 执行 restore 恢复系统环境(还原自动登录/开机自启等配置)..."
                                sh """
                                ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} '
                                    cd ${remoteDir}/IO_Stress && bash ./Fio_All.sh -i restore || true
                                '
                                """

                                echo "[${ip}] 4. 清理临时目录..."
                                sh "ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} 'rm -rf ${remoteDir}' || true"

                                echo "[${ip}] ✅ 测试已停止，系统环境已恢复。"
                            }
                        }
                    }
                    // 并发对所有节点执行停止与清理
                    parallel restoreTasks
                }
            }
        }

        stage('执行阶段：集群并发测试') {
            when { expression { return !params.RESTORE } }
            steps {
                script {
                    def parallelTasks = [:]
                    
                    for (int i = 0; i < targetIPs.size(); i++) {
                        def ip = targetIPs[i] 
                        
                        parallelTasks["Node_${ip}"] = {
                            stage("Test on ${ip}") {
                                // 每次构建使用独立的远程工作目录，避免多次构建互相污染
                                def remoteDir = "/root/Cyril/Jenkins/jenkins_nvme_${env.BUILD_NUMBER}"
                                
                                echo "[${ip}] 1. 部署代码..."
                                sh "ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} 'rm -rf ${remoteDir} && mkdir -p ${remoteDir}'"
                                // 排除 kernel_driver 源码大目录（其部署/编译由上方占位阶段后续实现）
                                sh "scp -o StrictHostKeyChecking=no -r \$(ls | grep -vx kernel_driver) ${env.TARGET_USER}@${ip}:${remoteDir}/"
                                
                                echo "[${ip}] 2. 安装 Python 依赖..."
                                // 部分系统(如 RHEL 9.x 最小化安装)自带 python3 但无 pip，
                                // 先按需引导 pip(ensurepip/包管理器)，再兼容新旧 pip 安装依赖。
                                sh """
                                ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} '
                                    cd ${remoteDir}
                                    python3 -m pip --version >/dev/null 2>&1 || python3 -m ensurepip --default-pip >/dev/null 2>&1 || true
                                    python3 -m pip --version >/dev/null 2>&1 || dnf install -y python3-pip >/dev/null 2>&1 || yum install -y python3-pip >/dev/null 2>&1 || apt-get install -y python3-pip >/dev/null 2>&1 || zypper install -y python3-pip >/dev/null 2>&1 || true
                                    python3 -m pip install -r requirements.txt --break-system-packages || python3 -m pip install -r requirements.txt
                                '
                                """
                                
                                echo "[${ip}] 3. 获取硬件环境信息..."
                                sh """
                                ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} '
                                    cd ${remoteDir}
                                    mkdir -p allure-results
                                    {
                                        echo "Node_${ip}_Host=\$(hostname)"
                                        echo "Node_${ip}_Kernel=\$(uname -r)"
                                        echo "Node_${ip}_NVMe_Count=\$(ls /dev/nvme*n1 2>/dev/null | wc -l)"
                                    } > allure-results/environment_${ip}.properties
                                '
                                """
                                
                                echo "[${ip}] 4. 运行母测试脚本 (nvme_raid_test.py)..."
                                // 测试项与全局配置均来自仓库内的 test_items.txt，无需再透传参数
                                sh """
                                ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} \"
                                    cd ${remoteDir} && \
                                    ALLOW_DESTRUCTIVE_FIO=${env.ALLOW_DESTRUCTIVE_FIO} \
                                    sudo -E python3 nvme_raid_test.py || true
                                \" 2>&1 | awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), \$0 }' | tee test_execution_${ip}.log
                                """
                                
                                echo "[${ip}] 5. 回传测试数据..."
                                sh """
                                mkdir -p allure-results
                                scp -o StrictHostKeyChecking=no -r ${env.TARGET_USER}@${ip}:${remoteDir}/allure-results/* ./allure-results/ || true
                                scp -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip}:${remoteDir}/report.xml ./report_${ip}.xml || true
                                """
                            }
                        }
                    }
                    // 触发并发执行所有主机的测试任务
                    parallel parallelTasks
                }
            }
        }

        stage('后期处理：测试环境属性合并') {
            when { expression { return !params.RESTORE } }
            steps {
                sh '''
                # 合并所有节点的属性文件
                cat allure-results/environment_*.properties > allure-results/environment.properties 2>/dev/null || true
                rm -f allure-results/environment_*.properties
                '''
            }
        }
    }

    post {
        always {
            script {
                // RESTORE(停止/清理)模式不产生测试报告，直接结束
                if (params.RESTORE) {
                    echo "🛑 停止与清理任务已完成，未执行测试，跳过报告生成与通知。"
                    return
                }

                sh 'sudo chown -R jenkins:jenkins . || true'

                // 聚合 JUnit XML 报告
                junit testResults: 'report_*.xml', allowEmptyResults: true

                // 生成 Allure 报告，并将标题设为 "TEST REPORT"
                allure(
                    includeProperties: true,
                    jdk: '',
                    reportName: 'TEST REPORT', 
                    results: [[path: 'allure-results']]
                )

                // 归档各节点的完整执行日志
                archiveArtifacts artifacts: 'test_execution_*.log', allowEmptyArchive: true

                // ===== 数据汇总统计 (Python) =====
                // 使用一次 Python 执行获取所有统计数据，避免重复启动环境和解析
                def metricsOutput = sh(script: """
                    python3 - << 'EOF'
import xml.etree.ElementTree as ET
import glob

stats = {'tests': 0, 'failures': 0, 'errors': 0, 'skipped': 0}
files = glob.glob('report_*.xml')
for f in files:
    try:
        t = ET.parse(f).getroot()
        for attr in stats.keys():
            val = int(t.attrib.get(attr) or sum(int(s.get(attr, 0)) for s in t.findall('.//testsuite')))
            stats[attr] += val
    except: pass
print(f"{stats['tests']} {stats['failures']} {stats['errors']} {stats['skipped']}")
EOF
                """, returnStdout: true).trim()

                def metrics = metricsOutput.split(' ')
                def total   = metrics[0].toInteger()
                def failed  = metrics[1].toInteger()
                def errors  = metrics[2].toInteger()
                def skipped = metrics[3].toInteger()

                def passed   = total - failed - errors - skipped
                def execRate = total > 0 ? String.format("%.2f%%", ((total - skipped) / (double) total) * 100) : "0%"
                def passRate = total > 0 ? String.format("%.1f%%", (passed / (double) total) * 100) : "0%"

                def startStr = new Date(currentBuild.startTimeInMillis).format("yyyy-MM-dd HH:mm:ss")
                def endStr   = new Date().format("yyyy-MM-dd HH:mm:ss")
                def statusColor = (failed + errors == 0 && total > 0) ? "blue" : "red"

                // ===== 飞书通知发送 =====
                // 发送时把集群节点 IP 加上
                def ipListStr = targetIPs.join(", ")
                def fontColor = statusColor == 'blue' ? 'green' : 'red'
                
                // 将 payload 写入本地文件进行发送，避免 curl 时终端解析导致引号被错误截断
                def payload = """
                {
                  "msg_type": "interactive",
                  "card": {
                    "config": { "wide_screen_mode": true },
                    "header": {
                      "title": { "tag": "plain_text", "content": "📊 NVMe_RAID(F6501) Test Report" },
                      "template": "${statusColor}"
                    },
                    "elements": [
                      {
                        "tag": "div",
                        "fields": [
                          { "is_short": true, "text": { "tag": "lark_md", "content": "**用户名:** dapustor" } },
                          { "is_short": true, "text": { "tag": "lark_md", "content": "**密码:** Admin@9000" } },
                          { "is_short": false, "text": { "tag": "lark_md", "content": "**时间周期：**\\n${startStr} ~ ${endStr}" } },
                          { "is_short": false, "text": { "tag": "lark_md", "content": "**并发节点：**\\n${ipListStr}" } },
                          { "is_short": false, "text": { "tag": "lark_md", "content": "**被测驱动(kernel_driver)：**\\n${kernelDriverCommit ?: '未知'}" } }
                        ]
                      },
                      {
                        "tag": "div",
                        "text": {
                          "tag": "lark_md",
                          "content": "✔️ **${passed}** ❌ **${failed}** ⛔ **${errors}** Total: **${total}**\\n执行率：${execRate}   通过率：<font color=\\"${fontColor}\\">${passRate}</font>"
                        }
                      },
                      {
                        "tag": "action",
                        "actions": [
                          {
                            "tag": "button",
                            "text": { "tag": "plain_text", "content": "查看详情" },
                            "url": "${env.BUILD_URL}allure/",
                            "type": "primary"
                          }
                        ]
                      }
                    ]
                  }
                }
                """
                
                writeFile file: 'feishu_payload.json', text: payload
                sh "curl -s -X POST -H 'Content-Type: application/json' -d @feishu_payload.json ${env.FEISHU_WEBHOOK}"
            }
        }
    }
}
