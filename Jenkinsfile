pipeline {
    agent any

    environment {
        // 【配置项】飞书机器人 Webhook 地址
        FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/17fe4cfd-5e49-4ceb-b8c4-f002d74340ee'
    }

    stages {
        stage('Clean & Checkout') {
            steps {
                // 1. 先清空工作空间，防止旧文件干扰
                cleanWs()
                // 2. 【关键修复】清空后必须重新拉取代码，否则后续步骤会找不到文件
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
                // 执行 FIO 测试：针对 nvme0n1, nvme1n1, nvme8n1 进行顺序/随机读写各 30s 的测试
                // 使用 awk 为日志增加物理时间戳，并使用 tee 确保 Allure 能“强制捕获”详细日志
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
            // 发布报告与归档日志
            junit 'report.xml'
            allure includeProperties: false, jdk: '', results: [[path: 'allure-results']]
            archiveArtifacts artifacts: 'test_execution.log', allowEmptyArchive: true

            script {
                // 获取构建时间戳
                def startStr = new Date(currentBuild.startTimeInMillis).format("yyyy-MM-dd HH:mm:ss")
                def endStr = new Date().format("yyyy-MM-dd HH:mm:ss")

                // 健壮的 XML 数据解析，统计测试项
                def getMetric = { attr ->
                    return sh(script: """
                        python3 -c "import xml.etree.ElementTree as ET; t=ET.parse('report.xml').getroot(); print(t.attrib.get('$attr') or sum(int(s.get('$attr',0)) for s in t.findall('.//testsuite')))"
                    """, returnStdout: true).trim()
                }

                def total = getMetric('tests')
                def failed = getMetric('failures')
                
                // 根据是否有失败决定卡片颜色（蓝色成功，红色失败）
                def statusColor = (failed == '0' && total != '0') ? "blue" : "red"

                // 构造飞书交互式卡片
                def payload = """
                {
                    "msg_type": "interactive",
                    "card": {
                        "config": { "wide_screen_mode": true },
                        "header": {
                            "title": { "tag": "plain_text", "content": "📊 RAID_NVME FIO 性能测试报告 - #${env.BUILD_NUMBER}" },
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
                // 发送给飞书机器人
                sh "curl -X POST -H 'Content-Type: application/json' -d '${payload}' ${env.FEISHU_WEBHOOK}"
            }
        }
    }
}
