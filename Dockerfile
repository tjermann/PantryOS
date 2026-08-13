# PantryOS — self-hosted meal planning.
#   docker compose up -d
# See GETTING-STARTED.md for the full walkthrough.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    PANTRYOS_USERS_DIR=/data/users \
    MEALPLANNER_USERS_DIR=/data/users \
    PANTRYOS_USER_INFO=/data/user_info.json \
    TZ=UTC

# cron isn't used in the container — the built-in scheduler handles timing —
# so the only system packages are what Chromium needs.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY service/pyproject.toml /app/pyproject.toml
COPY service/mealplanner /app/mealplanner
COPY service/starter-recipes /app/starter-recipes
COPY service/sample_user_info.json /app/sample_user_info.json

RUN pip install --no-cache-dir -e . \
    && python -m playwright install --with-deps chromium

VOLUME ["/data"]
EXPOSE 8321

# Runs the family web page and the schedule in one process.
CMD ["python", "-m", "mealplanner", "scheduler", "--serve"]
