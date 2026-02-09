pipeline {
    agent any
    environment {
        FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/17fe4cfd-5e49-4ceb-b8c4-f002d74340ee'
    }
    stages {
        stage('Checkout') {
            steps { echo '正在拉取代码...' }
        }
        stage('Install Dependencies') {
            steps { sh 'pip install -r requirements.txt' }
        }
        stage('Run Tests') {
            steps {
                // 执行测试并为日志文件增加时间戳
                sh '''
                pytest --alluredir=./allure-results --junitxml=report.xml 2>&1 | \
                awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), $0 }' > test_execution.log || true
                '''
            }
        }
    }
    post {
        always {
            junit 'report.xml'
            allure includeProperties: false, jdk: '', results: [[path: 'allure-results']]
            archiveArtifacts artifacts: 'test_execution.log', allowEmptyArchive: true
            
            script {
                // 1. 获取时间戳
                def startStr = new Date(currentBuild.startTimeInMillis).format("yyyy-MM-dd HH:mm:ss")
                def endStr = new Date().format("yyyy-MM-dd HH:mm:ss")

                // 2. 健壮的 XML 数据抓取（解决统计为 0 的问题）
                def total = sh(script: "python3 -c \"import xml.etree.ElementTree as ET; t=ET.parse('report.xml').getroot(); print(t.attrib.get('tests') or sum(int(s.get('tests',0)) for s in t.findall('.//testsuite')))\"", returnStdout: true).trim()
                def failed = sh(script: "python3 -c \"import xml.etree.ElementTree as ET; t=ET.parse('report.xml').getroot(); print(t.attrib.get('failures') or sum(int(s.get('failures',0)) for s in t.findall('.//testsuite')))\"", returnStdout: true).trim()
                
                // 3. 飞书卡片构造
                def payload = """
                {
                    "msg_type": "interactive",
                    "card": {
                        "config": { "wide_screen_mode": true },
                        "header": {
                            "title": { "tag": "plain_text", "content": "🔔 RAID_NVME 测试报告 - #${env.BUILD_NUMBER}" },
                            "template": "${failed == '0' ? 'blue' : 'red'}"
                        },
                        "elements": [
                            {
                                "tag": "div",
                                "fields": [
                                    { "is_short": true, "text": { "tag": "lark_md", "content": "**开始时间：**\\n${startStr}" } },
                                    { "is_short": true, "text": { "tag": "lark_md", "content": "**结束时间：**\\n${endStr}" } },
                                    { "is_short": true, "text": { "tag": "lark_md", "content": "**测试统计：**\\n总数: ${total} | 失败: ${failed}" } },
                                    { "is_short": true, "text": { "tag": "lark_md", "content": "**构建分支：**\\n${env.BRANCH_NAME ?: 'dev'}" } }
                                ]
                            },
                            {
                                "tag": "action",
                                "actions": [
                                    { "tag": "button", "text": { "tag": "plain_text", "content": "查看 Allure 报告" }, "url": "${env.BUILD_URL}allure/", "type": "primary" }
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
