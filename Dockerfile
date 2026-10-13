# Always-on deployment:
#   docker build -t asana-tracker .
#   docker run -d --restart=always -e BOT_TOKEN=... -e CHAT_ID=... [-e LLM_API_KEY=...] \
#     -v tracker-data:/data asana-tracker
FROM python:3.12-slim
WORKDIR /app
COPY tracker.py ./
ENV STATE_FILE=/data/state.json PYTHONUNBUFFERED=1
VOLUME /data
CMD ["python", "tracker.py", "--loop"]
