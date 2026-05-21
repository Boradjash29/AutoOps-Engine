FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y docker.io curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p logs && useradd -m -u 1000 autoops && chown -R autoops:autoops /app

ENV PORT=10000
ENV PYTHONUNBUFFERED=1

CMD uvicorn render_app:app --host 0.0.0.0 --port $PORT
