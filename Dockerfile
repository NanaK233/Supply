# Always-on deployment image. Pure Python standard library — no pip installs.
FROM python:3.12-slim

# Timezone so the daily scheduler's "08:00" means 8am your time.
ENV TZ=Asia/Dubai

WORKDIR /app
COPY . /app

# Persistent data (SQLite DB, session secret, scheduler state) lives here.
# Mount a volume at /data on your host so it survives redeploys.
ENV RESTOCK_DATA_DIR=/data
RUN mkdir -p /data

# The web server binds to $PORT (hosts set this automatically).
ENV PORT=8080
EXPOSE 8080

CMD ["python", "app.py"]
