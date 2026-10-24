# SkyLens - CLI / ETL / tests in a container.  (GUI inside Docker needs an X server - see README "Docker".)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg QT_QPA_PLATFORM=offscreen

# Qt (PySide6) needs these shared libraries even in offscreen mode.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libegl1 libxkbcommon0 libdbus-1-3 libfontconfig1 libglib2.0-0 libxcb-cursor0 \
        libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# notebooks are not needed in the image
RUN grep -vE "^(jupyter|nbconvert|ipykernel)" requirements.txt > /tmp/req.txt && pip install --no-cache-dir -r /tmp/req.txt

COPY . .

# Persist the database, archives and outputs on host volumes (see docker-compose.yml).
VOLUME ["/app/database", "/app/data", "/app/outputs"]

# Default: run the test-suite (no network / keys needed). Override the command to run other tools, e.g.
#   docker run --rm --env-file .env -v skylens-db:/app/database skylens python main_task/run_pipeline.py --inspect
CMD ["python", "-m", "pytest", "tests", "-q"]
