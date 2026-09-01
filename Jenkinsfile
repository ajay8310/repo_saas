pipeline {
    agent any

    parameters {
        string(name: 'BRANCH', defaultValue: 'develop', description: 'Enter the branch name')
    }

    environment {
        GIT_URL = 'https://openforge.gov.in/plugins/git/naddl/repo_saas.git'
        JENKINS_CREDENTIALS_ID = "bce92955-0760-423f-b323-64f6ff2dcda7"
        AWS_ACCOUNT_ID = "973759795388"
        AWS_DEFAULT_REGION = "ap-south-2"

        // ECR repositories (one per image)
        BACKEND_REPO_NAME = "repo_saas_dev_backend"
        FRONTEND_REPO_NAME = "repo_saas_dev_frontend"
        REGISTRY = "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_DEFAULT_REGION}.amazonaws.com"
        BACKEND_URI = "${REGISTRY}/${BACKEND_REPO_NAME}"
        FRONTEND_URI = "${REGISTRY}/${FRONTEND_REPO_NAME}"
        TAG_NAME = "dev"

        // ECS
        ECS_CLUSTER = "dev-nad"
        API_SERVICE = "repo_saas_dev_api"
        WORKER_SERVICE = "repo_saas_dev_worker"
        BEAT_SERVICE = "repo_saas_dev_beat"
        FRONTEND_SERVICE = "repo_saas_dev_frontend"
        API_TASK = "repo_saas_dev_api"
        WORKER_TASK = "repo_saas_dev_worker"
        BEAT_TASK = "repo_saas_dev_beat"
        FRONTEND_TASK = "repo_saas_dev_frontend"
        MIGRATE_TASK = "repo_saas_dev_migrate"

        // Networking for the one-off migrate run-task
        SUBNETS = "subnet-xxxxxxx,subnet-yyyyyyy"
        SECURITY_GROUP = "sg-xxxxxxx"
    }

    stages {

        stage('Clone Git') {
            steps {
                checkout([$class: 'GitSCM',
                    branches: [[name: "*/${params.BRANCH}"]],
                    extensions: [],
                    userRemoteConfigs: [[credentialsId: "${JENKINS_CREDENTIALS_ID}", url: "${GIT_URL}"]]
                ])
            }
        }

        stage('Login to AWS ECR') {
            steps {
                sh "aws ecr get-login-password --region ${AWS_DEFAULT_REGION} | docker login --username AWS --password-stdin ${REGISTRY}"
            }
        }

        stage('Build & Push Backend') {
            steps {
                sh """
                    docker build -f deploy/backend/Dockerfile -t ${BACKEND_URI}:${TAG_NAME} .
                    docker push ${BACKEND_URI}:${TAG_NAME}
                    docker rmi ${BACKEND_URI}:${TAG_NAME}
                """
            }
        }

        stage('Build & Push Frontend') {
            steps {
                sh """
                    docker build -f deploy/frontend/Dockerfile -t ${FRONTEND_URI}:${TAG_NAME} .
                    docker push ${FRONTEND_URI}:${TAG_NAME}
                    docker rmi ${FRONTEND_URI}:${TAG_NAME}
                """
            }
        }

        stage('Run Migrations') {
            steps {
                sh """
                    TASK_ARN=\$(aws ecs run-task \
                        --cluster ${ECS_CLUSTER} \
                        --task-definition ${MIGRATE_TASK} \
                        --launch-type FARGATE \
                        --network-configuration "awsvpcConfiguration={subnets=[${SUBNETS}],securityGroups=[${SECURITY_GROUP}],assignPublicIp=DISABLED}" \
                        --region ${AWS_DEFAULT_REGION} \
                        --query 'tasks[0].taskArn' --output text)

                    echo "Migration task: \${TASK_ARN}"
                    aws ecs wait tasks-stopped --cluster ${ECS_CLUSTER} --tasks \${TASK_ARN} --region ${AWS_DEFAULT_REGION}

                    EXIT_CODE=\$(aws ecs describe-tasks --cluster ${ECS_CLUSTER} --tasks \${TASK_ARN} \
                        --region ${AWS_DEFAULT_REGION} \
                        --query 'tasks[0].containers[0].exitCode' --output text)
                    if [ "\${EXIT_CODE}" != "0" ]; then
                        echo "Migration FAILED (exit \${EXIT_CODE})"; exit 1
                    fi
                    echo "Migration OK"
                """
            }
        }

        stage('Deploy Services') {
            steps {
                sh """
                    aws ecs update-service --region ${AWS_DEFAULT_REGION} --cluster ${ECS_CLUSTER} --service ${API_SERVICE} --task-definition ${API_TASK} --force-new-deployment
                    aws ecs update-service --region ${AWS_DEFAULT_REGION} --cluster ${ECS_CLUSTER} --service ${WORKER_SERVICE} --task-definition ${WORKER_TASK} --force-new-deployment
                    aws ecs update-service --region ${AWS_DEFAULT_REGION} --cluster ${ECS_CLUSTER} --service ${BEAT_SERVICE} --task-definition ${BEAT_TASK} --force-new-deployment
                    aws ecs update-service --region ${AWS_DEFAULT_REGION} --cluster ${ECS_CLUSTER} --service ${FRONTEND_SERVICE} --task-definition ${FRONTEND_TASK} --force-new-deployment
                """
            }
        }

        stage('Clean Workspace') {
            steps {
                deleteDir()
            }
        }
    }

    post {
        always {
            echo 'Pipeline completed. Cleaning workspace...'
            cleanWs()
        }
        failure {
            echo 'Pipeline failed!'
        }
        success {
            echo 'Pipeline completed successfully!'
        }
    }
}
