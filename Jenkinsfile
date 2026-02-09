pipeline {
    agent any

    environment {
        // 【配置项】请确保替换为你真实的飞书 Webhook 地址
        FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/17fe4cfd-5e49-4ceb-b8c4-f002d74340ee'
    }

    stages {
        stage('Clean & Checkout') {
            steps {
                // 1. 彻底清理工作空间，删除所有旧的残留文件（包括残留的 allure-results）
                cleanWs()
                echo '工作空间已清理，正在拉取最新代码...'
            }
        }

        stage('Install Dependencies') {
            steps {
                // 2. 安装项目依赖
                sh 'pip install -r requirements.txt'
            }
        }

        stage('Run FIO Tests') {
            steps {
                // 3. 执行 FIO 硬盘测试，使用“强制捕获”模式并生成带时间戳的详细日志
                // 针对 nvme0n1, nvme1n1, nvme8n1 进行顺序/随机读写各 30s 的测试
                sh '''
                pytest test_fio.py --alluredir=./allure-results --junitxml=report.xml \
                -o log_cli=true -o log_cli_level=INFO \
                2>&1 | awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), $0 }' | tee test_execution.log || true
                '''
            }
        }
    }

    post {
        always {
            // 4. 发布结果：由于使用了 cleanWs()，现在的 allure 报告里绝对不会再有 test_app 了
            junit 'report.xml'
            allure includeProperties: false, jdk: '', results: [[path: 'allure-results']]
            archiveArtifacts artifacts: 'test_execution.log', allowEmptyArchive: true

            script {
                // 5. 获取精确的时间戳和测试指标发送给飞书
                def startStr = new Date(currentBuild.startTimeInMillis).format("yyyy-MM-dd HH:mm:ss")
                def endStr = new Date().format("yyyy-MM-dd HH:mm:ss")

                def total = sh(script: "python3 -c \"import xml.etree.ElementTree as ET; t=ET.parse('report.xml').getroot(); print(t.attrib.get('tests') or sum(int(s.get('tests',0)) for s in t.findall('.//testsuite')))\"", returnStdout: true).trim()
                def failed = sh(script: "python3 -c \"import xml.etree.ElementTree as ET; t=ET.parse('report.xml').getroot(); print(t.attrib.get('failures') or sum(int(s.get('failures',0)) for s in t.findall('.//testsuite')))\"", returnStdout: true).trim()
                
                def statusColor = (failed == '0' && total != '0') ? "blue" : "red"

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
