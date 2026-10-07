FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -U -r requirements.txt
COPY app.py .
CMD gunicorn -b 0.0.0.0:${PORT:-8080} --timeout 600 --workers 2 --threads 4 app:app
