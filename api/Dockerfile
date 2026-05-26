FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
COPY build_db.py .
COPY ranking.py .
COPY entrypoint.sh .
COPY rag_mod.py .
COPY embed.py .
COPY rag_static ./rag_static
RUN chmod +x entrypoint.sh
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1
ENTRYPOINT ["./entrypoint.sh"]
