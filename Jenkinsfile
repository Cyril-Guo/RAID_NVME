pipeline {
    agent any

    environment {
        // 【配置项】飞书机器人 Webhook 地址
        FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/17fe4cfd-5e49-4ceb-b8c4-f002d74340ee'
    }

    stages {
        stage('Clean & Checkout') {
            steps {
                // 清理工作空间并重新拉取代码，确保 requirements.txt 等文件存在
                cleanWs()
                checkout scm 
                echo '工作空间已清理并重新拉取最新代码'
            }
        }

        stage('Install Dependencies') {
            steps {
                // 安装 Python 依赖
                sh 'pip install -r requirements.txt'
            }
        }

        stage('Run FIO Tests') {
            steps {
                // 使用 sudo 执行以获得 NVMe 设备权限
                // 建议在 test_fio.py 中为 fio 添加 --size=1G 以修复 nvme8n1 报错
                sh '''
                sudo pytest test_fio.py --alluredir=./allure-results --junitxml=report.xml \
                -o log_cli=true -o log_cli_level=INFO \
                2>&1 | awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), $0 }' | tee test_execution.log || true
                '''
            }
        }
    }

    post {
        always {
            script {
                // 1. 权限归还：将 root 生成的文件所有权交还给 jenkins 用户
                sh 'sudo chown -R jenkins:jenkins . || true'
                
                // 2. 【核心改进】：允许测试报告为空，防止找不到文件时中止后续飞书通知
                junit testResults: 'report.xml', allowEmptyResults: true 
                
                // 3. 发布 Allure 报告与日志归档
                allure includeProperties: false, jdk: '', results: [[path: 'allure-results']]
                archiveArtifacts artifacts: 'test_execution.log', allowEmptyArchive: true

                // 4. 获取时间戳与测试指标
                def startStr = new Date(currentBuild.startTimeInMillis).format("yyyy-MM-dd HH:mm:ss")
                def endStr = new Date().format("yyyy-MM-dd HH:mm:ss")

                // 安全地解析 XML，如果文件不存在则返回 0
                def getMetric = { attr ->
                    def exists = sh(script: "[ -f report.xml ] && echo 'yes' || echo 'no'", returnStdout: true).trim()
                    if (exists == 'no') return "0"
                    return sh(script: """
                        python3 -c "import xml.etree.ElementTree as ET; t=ET.parse('report.xml').getroot(); print(t.attrib.get('$attr') or sum(int(s.get('$attr',0)) for s in t.findall('.//testsuite')))"
                    """, returnStdout: true).trim()
                }

                def total = getMetric('tests')
                def failed = getMetric('failures')
                def statusColor = (failed == '0' && total != '0') ? "blue" : "red"

                // 5. 构造并发送飞书交互式卡片
                def payload = """
                {
                    "msg_type": "interactive",
                    "card": {
                        "config": { "wide_screen_mode": true },
                        "header": {
                            "title": { "tag": "plain_text", "content": "📊 RAID_NVME 测试报告 - #${env.BUILD_NUMBER}" },
                            "template": "${statusColor}"
                        },
                        "elements": [
                            {
                                "tag": "div",
                                "fields": [
                                    { "is_short": true, "text": { "tag": "lark_md", "content": "**开始时间：**\\n${startStr}" } },
                                    { "is_short": true, "text": { "tag": "lark_md", "content": "**结束时间：**\\n${endStr}" } },
                                    { "is_short": true, "text": { "tag": "lark_md", "content": "**测试统计：**\\n总数: ${total} | 失败: ${failed}" } },
                                    { "is_short": true, "text": { "tag": "lark_md", "content": "**构建分支：**\\ndev" } }
                                ]
                            },
                            {
                                "tag": "action",
                                "actions": [
                                    { "tag": "button", "text": { "tag": "plain_text", "content": "查看 Allure 详情报告" }, "url": "${env.BUILD_URL}allure/", "type": "primary" }
                                ]
                            }
                        ]
                    }
                }
                """
                sh "curl -X POST -H 'Content-Type: application/json' -d '${payload}' ${env.FEISHU_WEBHOOK}"
            }
        }
    }
}
