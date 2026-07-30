FROM python:3.11-slim

# System deps — gcc required for cryptography/telethon
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev libssl-dev curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# App
COPY . .

# Install as a package (provides tg-tools CLI)
RUN pip install --no-cache-dir -e .

# Temp directory for forwarder downloads
RUN mkdir -p /tmp/telegram_tools_forwarder && chmod 777 /tmp/telegram_tools_forwarder

EXPOSE 7860

# Default: launch Gradio web UI
CMD ["python", "app.py"]
