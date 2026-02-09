pipeline {
    agent any
    environment {
        FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/17fe4cfd-5e49-4ceb-b8c4-f002d74340ee'
    }

    stages {
        stage('Checkout') {
            steps {
                echo '正在拉取代码...'
            }
        }
        stage('Install') {
            steps {
                sh 'pip install -r requirements.txt'
            }
        }
        stage('Run Tests') {
            steps {
                // 暂时不重定向日志，以便在控制台确认 Pytest 是否发现用例
                // 如果你的测试文件在特定目录，请在此处加上目录名，例如 pytest tests/ ...
                sh 'pytest --alluredir=./allure-results --junitxml=report.xml || true'
            }
        }
    }

    post {
        always {
            junit 'report.xml'
            allure includeProperties: false, jdk: '', results: [[path: 'allure-results']]
            
            script {
                // 使用更强大的 Python 脚本解析 XML，确保能拿到嵌套的统计数据
                def getMetric = { attr ->
                    return sh(script: """
                        python3 -c "
import xml.etree.ElementTree as ET
try:
    tree = ET.parse('report.xml')
    root = tree.getroot()
    # 优先从根节点获取，如果没有则遍历子节点求和
    val = root.attrib.get('$attr')
    if val is None:
        val = sum(int(node.get('$attr', 0)) for node in root.findall('.//testsuite'))
    print(val)
except:
    print(0)
"
                    """, returnStdout: true).trim()
                }

                def total = getMetric('tests')
                def failed = getMetric('failures')
                def skipped = getMetric('skipped')
                def errors = getMetric('errors')
                
                // 计算通过率
                def passRate = "0%"
                if (total.toInteger() > 0) {
                    def passed = total.toInteger() - failed.toInteger() - errors.toInteger() - skipped.toInteger()
                    passRate = String.format("%.1f%%", (passed / total.toDouble()) * 100)
                }

                def statusColor = (failed.toInteger() + errors.toInteger() == 0 && total.toInteger() > 0) ? "blue" : "red"

                def payload = """
                {
                    "msg_type": "interactive",
                    "card": {
                        "config": { "wide_screen_mode": true },
                        "header": {
                            "title": { "tag": "plain_text", "content": "🔔 RAID_NVME 测试提醒 - #${env.BUILD_NUMBER}" },
                            "template": "${statusColor}"
                        },
                        "elements": [
                            {
                                "tag": "div",
                                "fields": [
                                    { "is_short": true, "text": { "tag": "lark_md", "content": "**构建分支：**\\n${env.BRANCH_NAME ?: 'dev'}" } },
                                    { "is_short": true, "text": { "tag": "lark_md", "content": "**测试统计：**\\n总数: ${total} | 失败: ${failed} | 跳过: ${skipped}" } },
                                    { "is_short": true, "text": { "tag": "lark_md", "content": "**通过率：**\\n${passRate}" } }
                                ]
                            },
                            {
                                "tag": "action",
                                "actions": [
                                    {
                                        "tag": "button",
                                        "text": { "tag": "plain_text", "content": "查看详情报告" },
                                        "url": "${env.BUILD_URL}allure/",
                                        "type": "primary"
                                    }
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
