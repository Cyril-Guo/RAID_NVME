pipeline {
    agent any

    stages {

        stage('Checkout') {
            steps {
                echo '拉代码'
            }
        }

        stage('Install Dependencies') {
            steps {
                sh 'pip install -r requirements.txt'
            }
        }

        stage('Run Tests') {
            steps {
                sh 'pytest --alluredir=./allure-results --junitxml=report.xml'
            }
        }
    }

    post {
        always {
            junit 'report.xml'
            allure includeProperties: false, jdk: '', results: [[path: 'allure-results']]
        }
    }
}

