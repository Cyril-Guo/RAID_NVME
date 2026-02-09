pipeline {
    agent any

    environment {
        // 【配置项】飞书机器人 Webhook 地址
        FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/17fe4cfd-5e49-4ceb-b8c4-f002d74340ee'
    }

    stages {
        stage('Clean & Checkout') {
            steps {
                // 清理工作空间并重新拉取代码，确保环境纯净
                cleanWs()
                checkout scm 
                echo '工作空间已清理并重新拉取代码'
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
                // 【核心变更】：使用 sudo 执行 pytest 以获得 /dev/nvme* 的读写权限
                // 建议在 test_fio.py 中为 fio 命令加上 --size=1G 参数以修复 nvme8n1 的报错
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
                // 【关键逻辑】：权限归还
                // 由于 Run Tests 使用了 sudo，生成的文件所有者是 root，此处必须改回 jenkins
                sh 'sudo chown -R jenkins:jenkins .'
                
                // 发布报告与归档日志
                junit 'report.xml'
                allure includeProperties: false, jdk: '', results: [[path: 'allure-results']]
                archiveArtifacts artifacts: 'test_execution.log', allowEmptyArchive: true

                // 获取时间戳和测试指标
                def startStr = new Date(currentBuild.startTimeInMillis).format("yyyy-MM-dd HH:mm:ss")
                def endStr = new Date().format("yyyy-MM-dd HH:mm:ss")

                def total = sh(script: "python3 -c \"import xml.etree.ElementTree as ET; t=ET.parse('report.xml').getroot(); print(t.attrib.get('tests') or sum(int(s.get('tests',0)) for s in t.findall('.//testsuite')))\"", returnStdout: true).trim()
                def failed = sh(script: "python3 -c \"import xml.etree.ElementTree as ET; t=ET.parse('report.xml').getroot(); print(t.attrib.get('failures') or sum(int(s.get('failures',0)) for s in t.findall('.//testsuite')))\"", returnStdout: true).trim()
                
                // 动态卡片颜色
                def statusColor = (failed == '0' && total != '0') ? "blue" : "red"

                // 发送飞书通知
                def payload = """
                {
                    "msg_type": "interactive",
                    "card": {
                        "config": { "wide_screen_mode": true },
                        "header": {
                            "title": { "tag": "plain_text", "content": "📊 RAID_NVME 性能测试报告 - #${env.BUILD_NUMBER}" },
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
                                    { "tag": "button", "text": { "tag": "plain_text", "content": "查看详情 (Allure)" }, "url": "${env.BUILD_URL}allure/", "type": "primary" }
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
