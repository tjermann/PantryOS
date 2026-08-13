"""Built-in scheduler — the container's answer to cron.

Runs the same weekly rhythm `install-cron` sets up on a host, but as one
long-lived process: every minute it checks whether a job is due and runs it.
Jobs are cheap no-ops on the wrong day, exactly as with cron.
"""

from __future__ import annotations

import threading
import time
import traceback
from datetime import datetime

# (hour, minutes, weekday or None for daily, job name)
SCHEDULE: list[tuple[int, list[int], int | None, str]] = [
    (20, [0], 3, "discover"),    # Thursday evening: new recipes
    (6, [15], None, "propose"),  # each morning; the job itself checks the day
    (9, [0], None, "iterate"),
    (12, [0], None, "iterate"),
    (15, [0], None, "iterate"),
    (18, [0], None, "iterate"),
    (6, [30], None, "weekly"),   # after propose, so they never collide
    (17, [0], 2, "restock"),     # Wednesday
    (15, [0], None, "tonight"),
    (8, [0], None, "inbox"),
    (18, [0], None, "inbox"),
]


def _run(job: str) -> None:
    from .config import list_users

    users = list_users()
    if job == "inbox":
        from .emailer.inbox import poll_inbox

        poll_inbox()
        return
    for user in users:
        if job == "discover":
            from .llm.client import client_for_user
            from .config import load_user_config
            from .recipes.discover import discover_all

            config = load_user_config(user)
            if config.recipe_sources:
                discover_all(client_for_user(config), user, config, total_limit=25)
        elif job == "propose":
            from .jobs.propose import run_propose

            run_propose(user)
        elif job == "iterate":
            from .jobs.propose import run_iterate

            run_iterate(user)
        elif job == "weekly":
            from .jobs.weekly import run_weekly

            run_weekly(user)
        elif job == "restock":
            from .jobs.restock import run_restock

            run_restock(user)
        elif job == "tonight":
            from .jobs.tonight import run_tonight

            run_tonight(user)


def run_scheduler(serve: bool = False, port: int = 8321) -> int:
    if serve:
        def _serve() -> None:
            import uvicorn

            from .web.app import create_app

            uvicorn.run(create_app(), host="0.0.0.0", port=port, log_level="warning")

        threading.Thread(target=_serve, daemon=True).start()
        print(f"family web page on port {port}", flush=True)

    print("scheduler running — " + ", ".join(
        f"{j}@{h:02d}:{m[0]:02d}" for h, m, _, j in SCHEDULE
    ), flush=True)
    last_fired: set[tuple[int, int, int, str]] = set()
    while True:
        now = datetime.now()
        for hour, minutes, weekday, job in SCHEDULE:
            if now.hour != hour or now.minute not in minutes:
                continue
            if weekday is not None and now.weekday() != weekday:
                continue
            stamp = (now.timetuple().tm_yday, hour, now.minute, job)
            if stamp in last_fired:
                continue
            last_fired.add(stamp)
            if len(last_fired) > 200:
                last_fired.clear()
            print(f"[{now:%Y-%m-%d %H:%M}] running {job}", flush=True)
            try:
                _run(job)
            except Exception:
                traceback.print_exc()
        time.sleep(30)
