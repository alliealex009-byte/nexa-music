FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

# ffmpeg for audio, deno = JavaScript runtime yt-dlp needs to solve YouTube's challenges
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg gcc build-essential git curl ca-certificates unzip \
    && curl -fsSL https://deno.land/install.sh | sh \
    && install -m 0755 /root/.deno/bin/deno /usr/local/bin/deno \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
CMD ["python", "app.py"]
