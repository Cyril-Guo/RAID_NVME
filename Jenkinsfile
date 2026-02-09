pipeline {
    agent any

    stages {
        stage('Checkout') {
            steps {
                // 这一步 Jenkins 会自动从 GitHub 拉取代码
                echo '拉取代码中...'
            }
        }

        stage('Install Dependencies') {
            steps {
                // 安装 Python 依赖
                sh 'pip install -r requirements.txt'
            }
        }

        stage('Run Tests') {
            steps {
                // 关键点：指定 --alluredir 目录，否则报告会是空的
                sh 'pytest --alluredir=./allure-results'
            }
        }
    }

    post {
        always {
            // 无论测试成功还是失败，都生成 Allure 报告
            allure includeProperties: false, jdk: '', results: [[path: 'allure-results']]
        }
    }
}
