FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY lclone ./lclone
COPY .env.example ./.env.example

ENV BRAIN_DB_PATH=/data/lclone.db
VOLUME /data

EXPOSE 8000

CMD ["python", "-c", "from lclone.web import run; run()"]
