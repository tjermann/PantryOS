"""mealplanner CLI — the deployer's interface. Household members use the web
UI (`mealplanner serve`) instead."""

from __future__ import annotations

import fcntl
import os
import sys
import time
from datetime import date
from pathlib import Path

import typer

from .config import list_users, load_user_config, user_dir

app = typer.Typer(help="Self-hosted meal planning: Claude plans, you approve.")


def _users(user: str | None, all_users: bool) -> list[str]:
    if all_users:
        users = list_users()
        if not users:
            typer.echo("No users found. Run: mealplanner setup")
            raise typer.Exit(1)
        return users
    if not user:
        typer.echo("Pass --user <name> or --all-users")
        raise typer.Exit(1)
    return [user]


# Jobs scheduled in the same minute contend for the user lock. Waiting for a
# turn is nearly always right: the loser is a job with real work to do, and
# skipping it silently costs a whole week (a missed Friday proposal, or worse,
# a Sunday cart that never loads).
LOCK_WAIT_S = 30 * 60


def _locked_run(user: str, fn, wait_s: int = LOCK_WAIT_S) -> int:
    lock_path = user_dir(user) / ".lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock:
        deadline = time.monotonic() + wait_s
        announced = False
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    print(f"[{user}] another run held the lock for "
                          f"{wait_s // 60}m; giving up", file=sys.stderr)
                    return 1
                if not announced:
                    print(f"[{user}] another run is in progress; waiting for it")
                    announced = True
                time.sleep(5)
        return fn(user)


def _run_for_each(users: list[str], fn) -> None:
    """Per-user isolation: one user's failure doesn't starve the rest."""
    failures = 0
    for u in users:
        try:
            failures += 1 if _locked_run(u, fn) != 0 else 0
        except Exception as exc:
            print(f"[{u}] FAILED: {exc}", file=sys.stderr)
            failures += 1
    if failures:
        raise typer.Exit(1)


@app.command()
def setup(user: str = typer.Option(None, help="Existing user to re-run setup for")):
    """Interactive questionnaire: household, diets, stores, budget, email."""
    from .setup_wizard import run_wizard

    run_wizard(user)


@app.command("run-weekly")
def run_weekly_cmd(
    user: str = typer.Option(None), all_users: bool = typer.Option(False, "--all-users"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the email, send nothing"),
    skip_carts: bool = typer.Option(False, "--skip-carts"),
    force: bool = typer.Option(False, "--force", help="Run even if today isn't planning day"),
):
    """Plan the week, build the list, load carts, email the household."""
    from .jobs.weekly import run_weekly

    _run_for_each(
        _users(user, all_users),
        lambda u: run_weekly(u, dry_run=dry_run, skip_carts=skip_carts, force=force),
    )


@app.command("run-propose")
def run_propose_cmd(
    user: str = typer.Option(None), all_users: bool = typer.Option(False, "--all-users"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    force: bool = typer.Option(False, "--force", help="Run even if today isn't proposal day"),
):
    """Email a proposed menu for family review (no shopping happens yet)."""
    from .jobs.propose import run_propose

    _run_for_each(_users(user, all_users),
                  lambda u: run_propose(u, dry_run=dry_run, force=force))


@app.command("run-iterate")
def run_iterate_cmd(
    user: str = typer.Option(None), all_users: bool = typer.Option(False, "--all-users"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """On proposal day: fold in new feedback and email a revised proposal."""
    from .emailer.inbox import poll_inbox
    from .jobs.propose import run_iterate

    # Pull in any email replies first so they count as feedback.
    try:
        poll_inbox()
    except Exception as exc:
        print(f"inbox poll failed (continuing): {exc}")
    _run_for_each(_users(user, all_users), lambda u: run_iterate(u, dry_run=dry_run))


@app.command("run-review")
def run_review_cmd(
    user: str = typer.Option(None), all_users: bool = typer.Option(False, "--all-users"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """Email a 'how was last week?' review of the meals actually cooked."""
    from .jobs.review import run_review

    _run_for_each(_users(user, all_users), lambda u: run_review(u, dry_run=dry_run))


@app.command("run-restock")
def run_restock_cmd(
    user: str = typer.Option(None), all_users: bool = typer.Option(False, "--all-users"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """Mid-week restock reminder email."""
    from .jobs.restock import run_restock

    _run_for_each(_users(user, all_users), lambda u: run_restock(u, dry_run=dry_run))


@app.command("run-tonight")
def run_tonight_cmd(
    user: str = typer.Option(None), all_users: bool = typer.Option(False, "--all-users"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """Tonight's dinner email with start-by time and cook notes."""
    from .jobs.tonight import run_tonight

    _run_for_each(_users(user, all_users), lambda u: run_tonight(u, dry_run=dry_run))


@app.command("run-inbox")
def run_inbox_cmd(dry_run: bool = typer.Option(False, "--dry-run")):
    """Read email replies from household members into planning feedback."""
    from .emailer.inbox import poll_inbox

    count = poll_inbox(dry_run=dry_run)
    typer.echo(f"{count} feedback message(s) processed")


@app.command("add-recipe")
def add_recipe_cmd(
    url: str = typer.Argument(..., help="Recipe page URL (blogs with structured recipe data)"),
    user: str = typer.Option(...),
):
    """Import a recipe from the web into this household's personal library."""
    from .llm.client import client_for_user
    from .recipes.webimport import import_from_url

    config = load_user_config(user)
    client = client_for_user(config)
    slug = import_from_url(client, user, url, model=config.model)
    typer.echo(f"Imported: {slug} — it's now part of {user}'s library and future plans.")


@app.command("discover-recipes")
def discover_recipes_cmd(
    user: str = typer.Option(None), all_users: bool = typer.Option(False, "--all-users"),
    limit: int = typer.Option(None, help="Max new recipes per source site"),
    total: int = typer.Option(None, help="Total budget across all sites (e.g. weekly 25)"),
):
    """Crawl the household's favorite recipe sites and import new recipes."""
    from .llm.client import client_for_user
    from .recipes.discover import discover_all

    def _one(u: str) -> int:
        config = load_user_config(u)
        if not config.recipe_sources:
            print(f"[{u}] no recipe_sources configured; skipping")
            return 0
        client = client_for_user(config)
        count = discover_all(client, u, config, limit_per_site=limit, total_limit=total)
        print(f"[{u}] imported {count} new recipes")
        return 0

    _run_for_each(_users(user, all_users), _one)


@app.command()
def login(
    user: str = typer.Option(...), store: str = typer.Option(...),
):
    """One-time store login in a visible browser (your credentials never touch us)."""
    from .carts.session import interactive_login

    raise typer.Exit(interactive_login(user, store))


@app.command("import-recipes")
def import_recipes_cmd(
    user: str = typer.Option(...),
    force: bool = typer.Option(False, "--force", help="Re-parse even if unchanged"),
):
    """Parse the recipe library into structured data (one Claude call per recipe)."""
    from .llm.client import client_for_user
    from .paths import parsed_cache_dir
    from .recipes.importer import import_entry
    from .recipes.library import load_library

    config = load_user_config(user)
    client = client_for_user(config)
    parsed_dir = parsed_cache_dir(user)
    entries = load_library(Path(config.recipe_library))
    counts: dict[str, int] = {}
    for i, entry in enumerate(entries, 1):
        outcome = import_entry(client, entry, parsed_dir, model=config.model, force=force)
        counts[outcome] = counts.get(outcome, 0) + 1
        typer.echo(f"[{i}/{len(entries)}] {entry.recipe.title}: {outcome}")
    typer.echo(f"Done: {counts}")


@app.command("write-directions")
def write_directions_cmd(user: str = typer.Option(...)):
    """AI-write directions for library recipes that have none (clearly labeled).
    Many imported libraries carry ingredients but point to a paywalled source
    for the steps — this fills the gap so every recipe is cookable."""
    from .llm.client import client_for_user
    from .paths import parsed_cache_dir
    from .recipes.importer import generate_directions
    from .recipes.library import load_library

    config = load_user_config(user)
    client = client_for_user(config)
    parsed_dir = parsed_cache_dir(user)
    entries = load_library(Path(config.recipe_library), parsed_dir)
    todo = [e for e in entries if not e.recipe.steps]
    typer.echo(f"{len(todo)} recipes lack directions")
    written = 0
    for i, entry in enumerate(todo, 1):
        if generate_directions(client, entry, parsed_dir, model=config.model):
            written += 1
            typer.echo(f"[{i}/{len(todo)}] {entry.recipe.title}: written")
        else:
            typer.echo(f"[{i}/{len(todo)}] {entry.recipe.title}: skipped")
    typer.echo(f"Done: {written} recipes now have directions (labeled AI-written).")


@app.command()
def rate(
    user: str = typer.Option(...),
    recipe: str = typer.Argument(..., help="Recipe title (fuzzy-matched)"),
    score: int = typer.Argument(..., min=1, max=5),
    real_time: int = typer.Option(None, "--real-time", help="Measured minutes, start to eating"),
    note: str = typer.Option(None, "--note"),
):
    """Record a rating (and optionally the real cook time + a note)."""
    slug = _resolve_slug(user, recipe)
    from .state.store import StateStore

    state = StateStore(user_dir(user)).record_rating(
        slug, score=score, real_time_min=real_time, note=note, made_on=date.today()
    )
    typer.echo(f"{slug}: rated {score}, lifecycle now {state.lifecycle}")


@app.command()
def request(
    user: str = typer.Option(...),
    recipes: list[str] = typer.Argument(None, help="Titles, slugs or source URLs"),
    dinners: int = typer.Option(None, "--dinners",
                                help="Total dinners that week, requested ones included"),
    week: str = typer.Option(None, "--week", help="ISO week, e.g. 2026-W43 (default: next)"),
    clear: bool = typer.Option(False, "--clear"),
):
    """Lock dishes into next week's menu ahead of the proposal; the proposal then
    offers options only for the nights that are left."""
    from .jobs.common import iso_week_of, next_week_dates
    from .state.store import StateStore

    config = load_user_config(user)
    week = week or iso_week_of(next_week_dates(date.today(), 1, config.planning_day)[0])
    store = StateStore(user_dir(user))
    if clear:
        store.set_requests(week, [], 0)
        typer.echo(f"{week}: requests cleared")
        return
    if not recipes:
        typer.echo(f"{week}: {store.load_requests(week) or 'no requests'}")
        return
    slugs = [_resolve_slug(user, r) for r in recipes]
    total = max(dinners or config.household.dinners_per_week, len(slugs))
    store.set_requests(week, slugs, total)
    typer.echo(f"{week}: {len(slugs)} locked in, options for {total - len(slugs)} more")
    for slug in slugs:
        typer.echo(f"  - {slug}")


@app.command()
def mark(
    user: str = typer.Option(...),
    recipe: str = typer.Argument(...),
    lifecycle: str = typer.Argument(..., help="to_try | probation | keeper | cut"),
):
    """Set a recipe's lifecycle. 'cut' keeps it in the library but never plans it."""
    if lifecycle not in ("to_try", "probation", "keeper", "cut"):
        raise typer.BadParameter("lifecycle must be to_try, probation, keeper, or cut")
    slug = _resolve_slug(user, recipe)
    from .state.store import StateStore

    StateStore(user_dir(user)).set_lifecycle(slug, lifecycle)
    typer.echo(f"{slug}: {lifecycle}")


@app.command("review-orders")
def review_orders_cmd(
    user: str = typer.Option(...),
    adjust: str = typer.Option(None, "--adjust", help="Free-text note on the latest order"),
    learn: str = typer.Option(None, "--learn", help="Add a standing learning for future planning"),
):
    """Show recent orders; record adjustments that feed future planning."""
    from .state.store import StateStore

    store = StateStore(user_dir(user))
    orders = store.load_orders()
    if not orders:
        typer.echo("No orders yet.")
        raise typer.Exit(0)
    for week, order in orders:
        carts = order.get("carts") or []
        summary = "; ".join(f"{c.get('store')}: {c.get('summary')}" for c in carts) or "no carts"
        n = len(order.get("grocery_lines") or [])
        review = f" | review: {order.get('review')}" if order.get("review") else ""
        typer.echo(f"{week}: {n} items | {summary}{review}")
    if adjust:
        week, order = orders[-1]
        order["review"] = f"{order.get('review') or ''}\n{adjust}".strip()
        store.save_order(week, order)
        typer.echo(f"Recorded on {week}: {adjust}")
    if learn:
        store.append_learning(learn)
        typer.echo("Added to standing learnings (used in future planning).")


@app.command()
def doctor(
    check_email: bool = typer.Option(False, "--check-email",
                                     help="Also try logging in to the email account"),
):
    """Check the whole setup and say exactly what to fix next."""
    from .doctor import run_doctor

    raise typer.Exit(run_doctor(check_email=check_email))


@app.command("validate-config")
def validate_config_cmd(
    user: str = typer.Option(None), all_users: bool = typer.Option(False, "--all-users"),
):
    """Validate config files and recipe-library paths."""
    ok = True
    for u in _users(user, all_users):
        try:
            config = load_user_config(u)
            library = Path(config.recipe_library)
            missing = [] if (library / "index.csv").exists() else ["recipe library index.csv"]
            if config.llm_backend == "claude-cli":
                import shutil

                if shutil.which(config.claude_cli_path) is None:
                    missing.append(f"claude CLI ('{config.claude_cli_path}' not on PATH)")
            if missing:
                typer.echo(f"[{u}] MISSING: {', '.join(missing)}")
                ok = False
            else:
                typer.echo(f"[{u}] ok ({len(config.stores)} stores, "
                           f"{len(config.household.people)} people)")
        except Exception as exc:
            typer.echo(f"[{u}] INVALID: {exc}")
            ok = False
    raise typer.Exit(0 if ok else 1)


@app.command("send-test-email")
def send_test_email_cmd(user: str = typer.Option(...)):
    """Verify SMTP credentials by sending a test message."""
    from .emailer.sender import send_email

    config = load_user_config(user)
    send_email(
        to=config.email.to,
        subject="Meal planner test email",
        text="SMTP is working. You're all set.",
        html="<p>SMTP is working. You're all set.</p>",
    )
    typer.echo(f"Sent to {', '.join(config.email.to)}")


@app.command("install-cron")
def install_cron_cmd(
    serve_port: int = typer.Option(8321, help="Port for the family feedback web page"),
):
    """Schedule PantryOS automatically (weekly plan, restock, tonight emails,
    and the family web page on reboot). Safe to re-run; only adds what's missing."""
    import subprocess
    import sys
    from .credentials import SERVICE_ROOT

    python = Path(sys.executable).resolve()
    prefix = f"cd {SERVICE_ROOT} && {python} -m mealplanner"
    wanted = {
        "pantryos-discover": f"0 20 * * 4 {prefix} discover-recipes --all-users --total 25 >> var/log/discover.log 2>&1",
        "pantryos-propose": f"15 6 * * * {prefix} run-propose --all-users >> var/log/propose.log 2>&1",
        "pantryos-iterate": f"0 9,12,15,18 * * * {prefix} run-iterate --all-users >> var/log/iterate.log 2>&1",
        # 30 minutes after propose: the two must never land in the same minute,
        # or they race for the user lock and one week's job silently loses.
        "pantryos-weekly": f"45 6 * * * {prefix} run-weekly --all-users >> var/log/weekly.log 2>&1",
        "pantryos-restock": f"0 17 * * 3 {prefix} run-restock --all-users >> var/log/restock.log 2>&1",
        "pantryos-tonight": f"0 15 * * * {prefix} run-tonight --all-users >> var/log/tonight.log 2>&1",
        "pantryos-inbox": f"0 8,18 * * * {prefix} run-inbox >> var/log/inbox.log 2>&1",
        # A page that dies between reboots should come back on its own.
        "pantryos-serve-watchdog": (
            f"*/5 * * * * cd {SERVICE_ROOT} && {python} -m mealplanner ensure-serve "
            f"--port {serve_port} >> var/log/serve.log 2>&1"
        ),
        # restart-serve, not serve: it health-checks and replaces a dead or
        # stale process instead of failing because the port looks taken.
        "pantryos-serve": (
            f"@reboot cd {SERVICE_ROOT} && {python} -m mealplanner restart-serve "
            f"--port {serve_port} >> var/log/serve.log 2>&1"
        ),
    }
    (SERVICE_ROOT / "var" / "log").mkdir(parents=True, exist_ok=True)
    current = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    lines = current.stdout.splitlines() if current.returncode == 0 else []
    added, updated = [], []
    for tag, entry in wanted.items():
        want = f"{entry}  # {tag}"
        existing = [i for i, l in enumerate(lines) if l.endswith(f"# {tag}")]
        if not existing:
            lines.append(want)
            added.append(tag)
        elif lines[existing[0]] != want:
            # An entry installed by an older version can be scheduled wrong
            # (jobs sharing a minute used to race); correct it in place.
            lines[existing[0]] = want
            updated.append(tag)
        for extra in reversed(existing[1:]):  # de-duplicate re-runs
            lines.pop(extra)
    if added or updated:
        subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True, check=True)
        if added:
            typer.echo(f"Scheduled: {', '.join(added)}")
        if updated:
            typer.echo(f"Corrected: {', '.join(updated)}")
    else:
        typer.echo("Already scheduled — nothing to do.")
    typer.echo("PantryOS will now plan each household's week on its planning day,")
    typer.echo("send restock and tonight emails, and keep the family page running.")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0"),
    port: int = typer.Option(8321),
    https: bool = typer.Option(False, help="Serve over HTTPS (self-signed certificate)"),
):
    """Run the household feedback web UI (ratings, notes, preferences)."""
    import uvicorn

    from .web.app import create_app

    kwargs = {}
    if https:
        from .web.certs import ensure_self_signed_cert

        cert, key = ensure_self_signed_cert()
        kwargs = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
    uvicorn.run(create_app(), host=host, port=port, **kwargs)


@app.command()
def scheduler(
    serve: bool = typer.Option(False, "--serve", help="Also run the family web page"),
    port: int = typer.Option(8321),
):
    """Run the weekly rhythm as a long-lived process (used by Docker)."""
    from .scheduler import run_scheduler

    raise typer.Exit(run_scheduler(serve=serve, port=port))


def _page_is_up(port: int) -> bool:
    import ssl
    import urllib.request

    insecure = ssl.create_default_context()
    insecure.check_hostname = False
    insecure.verify_mode = ssl.CERT_NONE
    for scheme, ctx in (("http", None), ("https", insecure)):
        try:
            with urllib.request.urlopen(
                f"{scheme}://127.0.0.1:{port}/", timeout=3, context=ctx
            ) as r:
                if r.status == 200:
                    return True
        except Exception:
            continue
    return False


@app.command("rebuild-leftovers")
def rebuild_leftovers_cmd(
    user: str = typer.Option(..., help="Household name"),
    dry_run: bool = typer.Option(False, help="Show the estimate without saving it"),
):
    """Estimate leftovers (opened sauces, spice jars, half onions) from recent
    orders. Safe to re-run: it only ever counts what the orders really bought."""
    from datetime import date

    from .config import user_dir
    from .grocery.leftovers import describe, on_hand, rebuild_from_history
    from .state.store import StateStore

    ledger = rebuild_from_history(user)
    rows = on_hand(ledger, date.today())
    if not rows:
        typer.echo("No leftovers found in recent orders.")
    for r in rows:
        typer.echo(f"  {r['name']} — {describe(r['qty'], r['unit'])} (good until {r['expires']})")
    if not dry_run:
        StateStore(user_dir(user)).save_leftovers(ledger)
        typer.echo(f"Saved {len(rows)} leftover item(s).")


@app.command("ensure-serve")
def ensure_serve_cmd(
    host: str = typer.Option("0.0.0.0"),
    port: int = typer.Option(8321),
):
    """Start the family web page only if it isn't answering. Safe to run every
    few minutes from cron: a healthy page is left completely alone."""
    from datetime import datetime

    stamp = f"[{datetime.now():%Y-%m-%d %H:%M}]"
    if _page_is_up(port):
        # Up, but possibly living inside a desktop session. systemd-oomd kills
        # whole cgroups under memory pressure, so a server started from a
        # terminal dies with that terminal. Restarting from here (cron, which
        # runs outside the user session) moves it somewhere it survives.
        if _in_user_session(_server_pids()) and not _in_user_session([os.getpid()]):
            typer.echo(f"{stamp} family page is inside a desktop session — moving it "
                       f"out of reach of the memory killer")
            restart_serve_cmd(host=host, port=port)
        return
    typer.echo(f"{stamp} family page was down — restarting")
    restart_serve_cmd(host=host, port=port)


def _stop_servers(timeout_s: float = 10.0) -> None:
    """Stop running family-page servers and wait until they are really gone.

    Matched on the server's exact argv rather than a pkill pattern: a pattern
    that starts with "-" is parsed as a pkill option and silently kills nothing,
    which then leaves the new server unable to bind the port."""
    import signal
    import time

    pids = [p for p in _server_pids() if p != os.getpid()]
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        alive = [p for p in pids if Path(f"/proc/{p}").exists()]
        if not alive:
            return
        time.sleep(0.25)
    for pid in alive:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    time.sleep(0.5)


def _server_pids() -> list[int]:
    pids = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            argv = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if b"mealplanner" in argv and b"serve" in argv and b"--host" in argv:
            pids.append(int(entry.name))
    return pids


def _in_user_session(pids: list[int]) -> bool:
    """True if any of these processes sits under the desktop user manager —
    the tree systemd-oomd sweeps."""
    for pid in pids:
        try:
            if "/user@" in Path(f"/proc/{pid}/cgroup").read_text():
                return True
        except OSError:
            continue
    return False


@app.command("restart-serve")
def restart_serve_cmd(
    host: str = typer.Option("0.0.0.0"),
    port: int = typer.Option(8321),
):
    """Cleanly restart the family web page (kills any stale copies first)."""
    import subprocess
    import sys
    import time

    from .credentials import SERVICE_ROOT

    _stop_servers()
    log_dir = SERVICE_ROOT / "var" / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    with open(log_dir / "serve.log", "ab") as log:
        subprocess.Popen(
            [sys.executable, "-m", "mealplanner", "serve", "--host", host,
             "--port", str(port)],
            cwd=SERVICE_ROOT, stdout=log, stderr=log, start_new_session=True,
        )
    for _ in range(20):
        time.sleep(0.5)
        if _page_is_up(port):
            typer.echo(f"Family page is up on port {port}.")
            return
    typer.echo("Started, but the health check didn't pass — see var/log/serve.log")
    raise typer.Exit(1)


def _resolve_slug(user: str, query: str) -> str:
    """Fuzzy-match a title against the user's library."""
    from .recipes.library import slugify
    from .recipes.merged import load_full_library

    config = load_user_config(user)
    entries = load_full_library(user, config.recipe_library)
    if query.startswith("http"):
        url = query.split("?")[0].rstrip("/")
        by_url = [e for e in entries if (e.source or "").split("?")[0].rstrip("/") == url]
        if by_url:
            return by_url[0].recipe.id
        typer.echo(f"No recipe imported from {query} — run add-recipe first")
        raise typer.Exit(1)
    q = slugify(query)
    exact = [e for e in entries if e.recipe.id == q]
    if exact:
        return exact[0].recipe.id
    partial = [e for e in entries if q in e.recipe.id]
    if len(partial) == 1:
        return partial[0].recipe.id
    if not partial:
        typer.echo(f"No recipe matching '{query}'")
        raise typer.Exit(1)
    typer.echo(f"Ambiguous — matches: {', '.join(e.recipe.id for e in partial[:8])}")
    raise typer.Exit(1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
