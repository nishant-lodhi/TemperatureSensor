# Container option — for ECS Fargate or EC2 deployment.
# Build from project root: docker build -f infra/Dockerfile -t tempmonitor-dashboard .

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY lambda_handler.py .

EXPOSE 8050

CMD ["gunicorn", "app.main:server", "-b", "0.0.0.0:8050", "-w", "2", "--timeout", "120"]
