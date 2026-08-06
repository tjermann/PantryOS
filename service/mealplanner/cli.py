"""mealplanner CLI — the deployer's interface. Household members use the web
UI (`mealplanner serve`) instead."""

from __future__ import annotations

import fcntl
import sys
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


def _locked_run(user: str, fn) -> int:
    lock_path = user_dir(user) / ".lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"[{user}] another run is in progress; skipping")
            return 0
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
        "pantryos-propose": f"15 6 * * * {prefix} run-propose --all-users >> var/log/propose.log 2>&1",
        "pantryos-iterate": f"0 9,12,15,18 * * * {prefix} run-iterate --all-users >> var/log/iterate.log 2>&1",
        "pantryos-weekly": f"15 6 * * * {prefix} run-weekly --all-users >> var/log/weekly.log 2>&1",
        "pantryos-restock": f"0 17 * * 3 {prefix} run-restock --all-users >> var/log/restock.log 2>&1",
        "pantryos-tonight": f"0 15 * * * {prefix} run-tonight --all-users >> var/log/tonight.log 2>&1",
        "pantryos-inbox": f"0 8,18 * * * {prefix} run-inbox >> var/log/inbox.log 2>&1",
        "pantryos-serve": (
            f"@reboot cd {SERVICE_ROOT} && nohup {python} -m mealplanner serve "
            f"--port {serve_port} >> var/log/serve.log 2>&1"
        ),
    }
    (SERVICE_ROOT / "var" / "log").mkdir(parents=True, exist_ok=True)
    current = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    lines = current.stdout.splitlines() if current.returncode == 0 else []
    added = []
    for tag, entry in wanted.items():
        if not any(tag in l for l in lines):
            lines.append(f"{entry}  # {tag}")
            added.append(tag)
    if added:
        subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True, check=True)
        typer.echo(f"Scheduled: {', '.join(added)}")
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


@app.command("restart-serve")
def restart_serve_cmd(
    host: str = typer.Option("0.0.0.0"),
    port: int = typer.Option(8321),
):
    """Cleanly restart the family web page (kills any stale copies first)."""
    import subprocess
    import sys
    import time
    import urllib.request

    from .credentials import SERVICE_ROOT

    subprocess.run(["pkill", "-f", "mealplanner serve"], capture_output=True)
    time.sleep(1.5)
    log_dir = SERVICE_ROOT / "var" / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    with open(log_dir / "serve.log", "ab") as log:
        subprocess.Popen(
            [sys.executable, "-m", "mealplanner", "serve", "--host", host,
             "--port", str(port)],
            cwd=SERVICE_ROOT, stdout=log, stderr=log, start_new_session=True,
        )
    import ssl

    insecure = ssl.create_default_context()
    insecure.check_hostname = False
    insecure.verify_mode = ssl.CERT_NONE
    for _ in range(20):
        time.sleep(0.5)
        for scheme, ctx in (("https", insecure), ("http", None)):
            try:
                with urllib.request.urlopen(
                    f"{scheme}://127.0.0.1:{port}/", timeout=3, context=ctx
                ) as r:
                    if r.status == 200:
                        typer.echo(f"Family page is up on {scheme}, port {port}.")
                        return
            except Exception:
                continue
    typer.echo("Started, but the health check didn't pass — see var/log/serve.log")
    raise typer.Exit(1)


def _resolve_slug(user: str, query: str) -> str:
    """Fuzzy-match a title against the user's library."""
    from .recipes.library import slugify
    from .recipes.merged import load_full_library

    config = load_user_config(user)
    entries = load_full_library(user, config.recipe_library)
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
