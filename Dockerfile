FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY brain ./brain
COPY .env.example ./.env.example

ENV BRAIN_DB_PATH=/data/brain.db
VOLUME /data

EXPOSE 8000

CMD ["python", "-c", "from brain.web import run; run()"]
