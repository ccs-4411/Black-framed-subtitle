FROM python:3.10-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["sh", "-c", "GRADIO_ANALYTICS_ENABLED=False GRADIO_SERVER_NAME=0.0.0.0 GRADIO_SERVER_PORT=${PORT:-7860} python app.py"]
