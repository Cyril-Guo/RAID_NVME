pipeline {
    agent any

    environment {
        // 请确保替换为你真实的飞书 Webhook 地址
        FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/17fe4cfd-5e49-4ceb-b8c4-f002d74340ee'
    }

    stages {
        stage('Checkout') {
            steps {
                echo '正在拉取代码...'
            }
        }

        stage('Install Dependencies') {
            steps {
                sh 'pip install -r requirements.txt'
            }
        }

        stage('Run Tests') {
            steps {
                // 【核心变更】：增加 -o log_cli=true 和 -o log_cli_level=INFO 
                // 这将强制 Pytest 捕获所有 INFO 级别及以上的日志并压入 Allure 报告
                // 2>&1 | tee test_execution.log 确保日志既能实时捕获，又能保存到本地文件供下载
                sh '''
                pytest --alluredir=./allure-results --junitxml=report.xml \
                -o log_cli=true -o log_cli_level=INFO \
                2>&1 | tee test_execution.log || true
                '''
            }
        }
    }

    post {
        always {
            // 生成 JUnit 和 Allure 报告
            junit 'report.xml'
            allure includeProperties: false, jdk: '', results: [[path: 'allure-results']]
            
            // 归档日志文件，方便在 Jenkins 界面点击下载
            archiveArtifacts artifacts: 'test_execution.log', allowEmptyArchive: true

            script {
                // 提取测试结果并发送飞书通知
                def total = sh(script: "python3 -c \"import xml.etree.ElementTree as ET; t=ET.parse('report.xml').getroot(); print(t.attrib.get('tests') or sum(int(s.get('tests',0)) for s in t.findall('.//testsuite')))\"", returnStdout: true).trim()
                def failed = sh(script: "python3 -c \"import xml.etree.ElementTree as ET; t=ET.parse('report.xml').getroot(); print(t.attrib.get('failures') or sum(int(s.get('failures',0)) for s in t.findall('.//testsuite')))\"", returnStdout: true).trim()
                
                def statusColor = (failed == '0' && total != '0') ? "blue" : "red"
                def payload = """
                {
                    "msg_type": "interactive",
                    "card": {
                        "config": { "wide_screen_mode": true },
                        "header": {
                            "title": { "tag": "plain_text", "content": "🔔 RAID_NVME 测试报告 - #${env.BUILD_NUMBER}" },
                            "template": "${statusColor}"
                        },
                        "elements": [
                            {
                                "tag": "div",
                                "fields": [
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
