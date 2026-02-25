// 全局数组，用于存储从 target_ips.txt 文件中读取的目标 IP 列表
def targetIPs = []

pipeline {
    agent any

    environment {
        // 全局配置区
        FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/17fe4cfd-5e49-4ceb-b8c4-f002d74340ee'
        TARGET_USER = 'root'
        //ALLOW_DESTRUCTIVE_FIO = '1' // <--- 加上这一行解锁写入测试 
    }

    stages {

        stage('Clean & Checkout & Read Targets') {
            steps {
                cleanWs()
                checkout scm
                
                script {
                    // 读取项目根目录下的 target_ips.txt
                    if (fileExists('target_ips.txt')) {
                        def ipContent = readFile('target_ips.txt').trim()
                        // 按行分割，过滤掉空行和以 # 开头的注释行
                        targetIPs = ipContent.split('\\r?\\n').findAll { it.trim() != '' && !it.startsWith('#') }
                        
                        if (targetIPs.size() == 0) {
                            error "target_ips.txt 中没有找到有效的 IP 地址，请检查文件内容！"
                        }
                        echo "获取到 ${targetIPs.size()} 台待测机器: ${targetIPs}"
                    } else {
                        error "未找到 target_ips.txt 文件，请在代码根目录创建该文件并写入目标 IP！"
                    }
                }
            }
        }

        stage('Parallel Execution On Cluster') {
            steps {
                script {
                    def parallelTasks = [:]
                    
                    // 遍历所有 IP，为每个 IP 动态生成一个独立的执行流
                    for (int i = 0; i < targetIPs.size(); i++) {
                        // 必须使用 def 声明局部变量，防止并发时变量名被后面的循环覆盖
                        def ip = targetIPs[i] 
                        
                        parallelTasks["Node_${ip}"] = {
                            stage("Test on ${ip}") {
                                // 每台机器的工作目录带上 Jenkins 构建号，防止多次构建产生的临时文件冲突
                                def remoteDir = "/tmp/jenkins_fio_${env.BUILD_NUMBER}"
                                
                                echo ">> [${ip}] 步骤 1: 清理远端并传输代码"
                                sh """
                                ssh ${env.TARGET_USER}@${ip} "rm -rf ${remoteDir} && mkdir -p ${remoteDir}"
                                scp -r * ${env.TARGET_USER}@${ip}:${remoteDir}/
                                """
                                
                                echo ">> [${ip}] 步骤 2: 安装依赖"
                                sh """
                                ssh ${env.TARGET_USER}@${ip} "cd ${remoteDir} && pip install -r requirements.txt"
                                """
                                
                                echo ">> [${ip}] 步骤 3: 收集节点环境信息"
                                // 将该机器的环境信息写入专属的 properties 文件中，键名带上 IP 防止合并时冲突
                                sh """
                                ssh ${env.TARGET_USER}@${ip} '
                                    cd ${remoteDir}
                                    mkdir -p allure-results
                                    {
                                        echo "Node_${ip}_Host=\$(hostname)"
                                        echo "Node_${ip}_Kernel=\$(uname -r)"
                                        echo "Node_${ip}_NVMe_Count=\$(ls /dev/nvme*n1 2>/dev/null | wc -l)"
                                    } > allure-results/environment_${ip}.properties
                                '
                                """
                                
                                echo ">> [${ip}] 步骤 4: 执行 FIO 测试"
                                // 运行测试，将控制台输出加上时间戳，并单独保存为该 IP 的本地日志文件
                                sh """
                                ssh ${env.TARGET_USER}@${ip} "cd ${remoteDir} && sudo pytest test_fio.py --alluredir=./allure-results --junitxml=report.xml -o log_cli=true -o log_cli_level=INFO || true" 2>&1 | awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), \$0 }' | tee test_execution_${ip}.log
                                """
                                
                                echo ">> [${ip}] 步骤 5: 拉取测试结果回中控机"
                                sh """
                                mkdir -p allure-results
                                # 拉回 Allure JSON 结果和环境文件
                                scp -r ${env.TARGET_USER}@${ip}:${remoteDir}/allure-results/* ./allure-results/ || true
                                # 将远端的 XML 报告重命名，防止覆盖其他机器的报告
                                scp ${env.TARGET_USER}@${ip}:${remoteDir}/report.xml ./report_${ip}.xml || true
                                """
                            }
                        }
                    }
                    
                    // 触发并发执行所有主机的测试任务
                    parallel parallelTasks
                }
            }
        }

        stage('Prepare Allure UI Patch & Merge Env') {
            steps {
                // 在中控机本地合并所有机器的环境信息，并注入自定义的 CSS/JS 补丁
                sh '''
                # 合并所有节点的 environment 属性到一个文件中
                cat allure-results/environment_*.properties > allure-results/environment.properties 2>/dev/null || true
                rm -f allure-results/environment_*.properties

                # ---------- custom.css ----------
                cat > allure-results/custom.css << 'EOF'
/* 隐藏无用的 Categories 分类 */
.side-menu__item[data-id="categories"],
.side-menu__item[data-id="category"] { display: none !important; }
.widget:has(.widget__title:contains("Categories")),
.widget:has(.widget__title:contains("类别")),
.widget:has(.widget__title:contains("Product defects")) { display: none !important; }
EOF

                # ---------- custom.js ----------
                cat > allure-results/custom.js << 'EOF'
/* 替换默认的测试套文案 */
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('*').forEach(el => {
    if (el.childNodes.length === 1 && el.innerText && el.innerText.trim() === '测试套') {
      el.innerText = '测试日志';
    }
  });
});
EOF
                '''
            }
        }
    }

    post {
        always {
            script {
                // 修复本地文件权限
                sh 'sudo chown -R jenkins:jenkins . || true'

                // 聚合所有节点的 XML 结果
                junit testResults: 'report_*.xml', allowEmptyResults: true

                // 生成 Allure 报告
                allure(
                    includeProperties: true,
                    jdk: '',
                    reportName: 'Cluster FIO Test Report',
                    results: [[path: 'allure-results']]
                )

                // 归档所有节点的独立运行日志
                archiveArtifacts artifacts: 'test_execution_*.log', allowEmptyArchive: true

                // ===== 使用 Python 脚本遍历并汇总所有节点的 XML 指标 =====
                def getMetric = { attr ->
                    return sh(script: """
                        python3 - << 'EOF'
import xml.etree.ElementTree as ET
import glob
val = 0
files = glob.glob('report_*.xml')
if not files:
    print(0)
else:
    for f in files:
        try:
            t = ET.parse(f).getroot()
            # 提取根节点属性，或累加 testsuite 子节点属性
            val += int(t.attrib.get('${attr}') or sum(int(s.get('${attr}',0)) for s in t.findall('.//testsuite')))
        except Exception:
            pass
print(val)
EOF
                    """, returnStdout: true).trim()
                }

                def total   = getMetric('tests').toInteger()
                def failed  = getMetric('failures').toInteger()
                def errors  = getMetric('errors').toInteger()
                def skipped = getMetric('skipped').toInteger()

                def passed   = total - failed - errors - skipped
                def execRate = total > 0 ? String.format("%.2f%%", ((total - skipped) / (double) total) * 100) : "0%"
                def passRate = total > 0 ? String.format("%.1f%%", (passed / (double) total) * 100) : "0%"

                def startStr = new Date(currentBuild.startTimeInMillis).format("yyyy-MM-dd HH:mm:ss")
                def endStr   = new Date().format("yyyy-MM-dd HH:mm:ss")
                def statusColor = (failed + errors == 0 && total > 0) ? "blue" : "red"

                // ===== 飞书卡片通知 =====
                def ipListStr = targetIPs.join(", ")
                def payload = """
                {
                  "msg_type": "interactive",
                  "card": {
                    "config": { "wide_screen_mode": true },
                    "header": {
                      "title": { "tag": "plain_text", "content": "📊 CI 测试 - #${env.BUILD_NUMBER}" },
                      "template": "${statusColor}"
                    },
                    "elements": [
                      {
                        "tag": "div",
                        "fields": [
                          { "is_short": false, "text": { "tag": "lark_md", "content": "**测试规模：** ${targetIPs.size()} 台节点并联执行\\n**目标机器：** ${ipListStr}" } },
                          { "is_short": false, "text": { "tag": "lark_md", "content": "**执行时间：** ${startStr} ~ ${endStr}" } }
                        ]
                      },
                      {
                        "tag": "div",
                        "text": {
                          "tag": "lark_md",
                          "content": "✔️ **${passed}** ❌ **${failed}** ⛔ **${errors}** Total: **${total}**\\n执行率：${execRate}   通过率：<font color='${statusColor == 'blue' ? 'green' : 'red'}'>${passRate}</font>"
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

                sh "curl -s -X POST -H 'Content-Type: application/json' -d '${payload}' ${env.FEISHU_WEBHOOK}"
            }
        }
    }
}
