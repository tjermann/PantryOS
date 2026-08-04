"""Household feedback web UI — the interface for non-technical family members.

Runs on the home LAN via `mealplanner serve`. No accounts: access control is
signed URLs. Each user's page lives at /u/<user>?t=<signed token>; emails link
there (and to one-click rating links). Tokens are HMAC-signed with a key kept
in users/<user>/.web_secret (auto-generated).

What a household member can do here:
  - rate recent dinners (one tap), add notes
  - mark keeper / cut
  - adjust preferences: budget, dinners per week, foods to avoid, spice-free
    text notes, standing items
Allergen/severity changes intentionally require the deployer (CLI setup) —
safety-critical config shouldn't change from an unauthenticated LAN page.
"""

from __future__ import annotations

import secrets
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import BadSignature, URLSafeSerializer

from ..config import list_users, load_user_config, save_user_config, user_dir
from ..recipes.library import load_library
from ..state.store import StateStore


def _secret_for(user: str, base: Path | None = None) -> str:
    path = user_dir(user, base) / ".web_secret"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32))
        path.chmod(0o600)
    return path.read_text().strip()


def _serializer(user: str, base: Path | None = None) -> URLSafeSerializer:
    return URLSafeSerializer(_secret_for(user, base), salt="mealplanner-web")


def feedback_url(user: str, base_url: str, base: Path | None = None) -> str:
    token = _serializer(user, base).dumps({"u": user})
    return f"{base_url}/u/{user}?t={token}"


def rating_url(user: str, base_url: str, slug: str, score: int, base: Path | None = None) -> str:
    token = _serializer(user, base).dumps({"u": user, "r": slug, "s": score})
    return f"{base_url}/rate/{user}?t={token}"


def recipe_url(user: str, base_url: str, slug: str, base: Path | None = None) -> str:
    token = _serializer(user, base).dumps({"u": user})
    return f"{base_url}/r/{user}/{slug}?t={token}"


def _check(user: str, token: str | None, base: Path | None = None) -> dict:
    if not token:
        raise HTTPException(403, "missing token — use the link from your email")
    try:
        data = _serializer(user, base).loads(token)
    except BadSignature:
        raise HTTPException(403, "bad token — use the link from your email")
    if data.get("u") != user:
        raise HTTPException(403, "token is for a different user")
    return data


PAGE = """<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Meal Planner</title><style>
body {{ font-family: Georgia, serif; max-width: 560px; margin: 0 auto; padding: 16px; color: #2b2b2b; }}
h1 {{ font-size: 20px; border-bottom: 2px solid #c96f4a; padding-bottom: 6px; }}
h2 {{ font-size: 16px; margin-top: 22px; }}
.card {{ border: 1px solid #ddd; border-radius: 8px; padding: 12px; margin: 10px 0; }}
.stars a {{ text-decoration: none; font-size: 22px; }}
button {{ background: #c96f4a; color: #fff; border: 0; border-radius: 4px; padding: 8px 14px; font-size: 14px; }}
input, textarea, select {{ width: 100%; box-sizing: border-box; padding: 6px; margin: 4px 0 10px; font-size: 14px; }}
.msg {{ background: #ecf7ec; border-left: 4px solid #5a5; padding: 8px 12px; }}
small {{ color: #888; }}
</style></head><body>{body}</body></html>"""


def create_app(base: Path | None = None) -> FastAPI:
    app = FastAPI(title="Meal Planner", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index():
        users = ", ".join(list_users(base)) or "none yet — run `mealplanner setup`"
        return PAGE.format(
            body=f"<h1>Meal Planner</h1><p>Users: {users}</p>"
                 "<p>Open your personal link from any planner email.</p>"
        )

    @app.get("/rate/{user}", response_class=HTMLResponse)
    def one_click_rate(user: str, t: str | None = None):
        data = _check(user, t, base)
        slug, score = data.get("r"), data.get("s")
        if not slug or not isinstance(score, int):
            raise HTTPException(400, "not a rating link")
        state = StateStore(user_dir(user, base)).record_rating(
            slug, score=score, made_on=date.today()
        )
        return PAGE.format(
            body=f"<h1>Thanks!</h1><div class='msg'>Recorded {'★' * score} for "
                 f"<strong>{slug}</strong> (now: {state.lifecycle}).</div>"
        )

    @app.get("/u/{user}", response_class=HTMLResponse)
    def user_page(user: str, t: str | None = None, saved: str | None = None):
        _check(user, t, base)
        config = load_user_config(user, base)
        store = StateStore(user_dir(user, base))
        s = _serializer(user, base)

        parts = [f"<h1>{config.name} — meal feedback</h1>"]
        if saved:
            parts.append(f"<div class='msg'>{saved}</div>")

        latest = store.latest_plan()
        parts.append("<h2>Rate recent dinners</h2>")
        if latest:
            _, plan = latest
            states = store.load_recipe_states()
            for entry in plan.get("entries", []):
                slug = entry.get("recipe_id")
                stars = " ".join(
                    f"<a href='/rate/{user}?t={s.dumps({'u': user, 'r': slug, 's': n})}'>"
                    f"{'★' * n}{'☆' * (5 - n)}</a>"
                    for n in range(1, 6)
                )
                current = states.get(slug)
                lifecycle = current.lifecycle if current else "to_try"
                keep_t = s.dumps({"u": user, "m": slug, "lc": "keeper"})
                cut_t = s.dumps({"u": user, "m": slug, "lc": "cut"})
                parts.append(
                    f"<div class='card'><strong>{slug.replace('-', ' ').title()}</strong> "
                    f"<small>({entry.get('date')}, now: {lifecycle})</small>"
                    f"<div class='stars'>{stars}</div>"
                    f"<form method='post' action='/note/{user}'>"
                    f"<input type='hidden' name='t' value='{t}'>"
                    f"<input type='hidden' name='slug' value='{slug}'>"
                    f"<input name='note' placeholder='Notes for next time (e.g. double the sauce)'>"
                    f"<button>Save note</button> "
                    f"<a href='/mark/{user}?t={keep_t}'>keep it coming</a> · "
                    f"<a href='/mark/{user}?t={cut_t}'>never again</a>"
                    f"</form></div>"
                )
        else:
            parts.append("<p><small>No plan yet — check back after the next weekly email.</small></p>")

        staples_list = store.load_staples()
        staple_rows = "".join(
            f"<li>{s} — "
            f"<form method='post' action='/staples/{user}' style='display:inline'>"
            f"<input type='hidden' name='t' value='{t}'>"
            f"<input type='hidden' name='item' value='{s}'>"
            f"<button name='action' value='restock' style='padding:2px 8px;font-size:12px'>ran out — buy this week</button> "
            f"<button name='action' value='remove' style='padding:2px 8px;font-size:12px;background:#999'>remove</button>"
            f"</form></li>"
            for s in staples_list
        ) or "<li><small>none yet</small></li>"
        parts.append(
            f"""<h2>Pantry staples (never auto-bought)</h2>
<div class='card'>
<p><small>Things you always have — salt, olive oil, spices. Recipes that use them
won't add them to the weekly order. Tap 'ran out' to buy one this week.</small></p>
<ul>{staple_rows}</ul>
<form method='post' action='/staples/{user}'>
<input type='hidden' name='t' value='{t}'>
<input name='item' placeholder='e.g. sea salt, cumin, olive oil'>
<button name='action' value='add'>Add staple</button>
</form>
</div>"""
        )

        budget_dollars = (config.household.budget_cents_weekly or 0) // 100
        checked = "checked" if config.household.budget_enabled else ""
        parts.append(
            f"""<h2>Preferences</h2>
<form method='post' action='/prefs/{user}' class='card'>
<input type='hidden' name='t' value='{t}'>
<label>Dinners per week</label>
<select name='dinners'>{''.join(f"<option {'selected' if n == config.household.dinners_per_week else ''}>{n}</option>" for n in range(1, 8))}</select>
<label><input type='checkbox' name='budget_enabled' style='width:auto' {checked}> Weekly budget</label>
<input type='number' name='budget_dollars' value='{budget_dollars or 200}' min='20' max='2000'>
<label>Requests for the planner <small>(free text — "more fish", "nothing spicy on weeknights")</small></label>
<textarea name='request' rows='3'></textarea>
<label>Add a standing grocery item <small>(bought every week)</small></label>
<input name='standing' placeholder='e.g. applesauce pouches'>
<button>Save preferences</button>
<p><small>Allergy changes are deliberately not editable here — ask whoever set the
planner up to run <code>mealplanner setup</code>.</small></p>
</form>"""
        )
        return PAGE.format(body="".join(parts))

    @app.get("/r/{user}/{slug}", response_class=HTMLResponse)
    def recipe_page(user: str, slug: str, t: str | None = None):
        _check(user, t, base)
        from ..paths import parsed_cache_dir
        from ..recipes.library import load_library

        config = load_user_config(user, base)
        entries = load_library(Path(config.recipe_library), parsed_cache_dir(user, base))
        entry = next((e for e in entries if e.recipe.id == slug), None)
        if entry is None:
            raise HTTPException(404, "recipe not found")
        recipe = entry.recipe
        parts = [f"<h1>{recipe.title}</h1>",
                 f"<p><small>Serves {recipe.serves}"
                 + (f" · ~{recipe.published_time_min} min" if recipe.published_time_min else "")
                 + "</small></p>"]
        if recipe.ingredients:
            parts.append("<h2>Ingredients</h2><ul>")
            parts.extend(f"<li>{i.raw}</li>" for i in recipe.ingredients)
            parts.append("</ul>")
        if recipe.steps:
            parts.append("<h2>Directions</h2><ol>")
            for s in recipe.steps:
                extra = []
                if s.duration_min:
                    extra.append(f"~{s.duration_min} min")
                if s.unattended:
                    extra.append("hands-off")
                suffix = f" <small>({', '.join(extra)})</small>" if extra else ""
                parts.append(f"<li>{s.text}{suffix}</li>")
            parts.append("</ol>")
        if not recipe.ingredients and entry.markdown_path.exists():
            body = entry.markdown_path.read_text()
            parts.append(f"<pre style='white-space:pre-wrap'>{body}</pre>")
        return PAGE.format(body="".join(parts))

    @app.post("/staples/{user}")
    def staples(user: str, t: str = Form(...), action: str = Form(...),
                item: str = Form("")):
        _check(user, t, base)
        store = StateStore(user_dir(user, base))
        current = store.load_staples()
        item = item.strip().lower()
        if action == "add" and item:
            store.save_staples([*current, item])
            msg = f"'{item}' marked as always-on-hand"
        elif action == "remove" and item in current:
            store.save_staples([s for s in current if s != item])
            msg = f"'{item}' will be bought when recipes need it"
        elif action == "restock" and item:
            store.add_restock(item)
            msg = f"'{item}' added to this week's shopping (still a staple)"
        else:
            msg = "No change"
        return RedirectResponse(f"/u/{user}?t={t}&saved={msg.replace(' ', '+')}",
                                status_code=303)

    @app.get("/mark/{user}", response_class=HTMLResponse)
    def mark(user: str, t: str | None = None):
        data = _check(user, t, base)
        slug, lifecycle = data.get("m"), data.get("lc")
        if not slug or lifecycle not in ("keeper", "cut"):
            raise HTTPException(400, "not a mark link")
        StateStore(user_dir(user, base)).set_lifecycle(slug, lifecycle)
        verdict = "will keep showing up" if lifecycle == "keeper" else "won't be planned again"
        return PAGE.format(
            body=f"<h1>Done</h1><div class='msg'><strong>{slug}</strong> {verdict}.</div>"
        )

    @app.post("/note/{user}")
    def note(user: str, t: str = Form(...), slug: str = Form(...), note: str = Form("")):
        _check(user, t, base)
        if note.strip():
            StateStore(user_dir(user, base)).record_rating(slug, note=note.strip())
        return RedirectResponse(f"/u/{user}?t={t}&saved=Note+saved", status_code=303)

    @app.post("/prefs/{user}")
    def prefs(
        user: str,
        t: str = Form(...),
        dinners: int = Form(...),
        budget_dollars: int = Form(200),
        request: str = Form(""),
        standing: str = Form(""),
        budget_enabled: str | None = Form(None),
    ):
        _check(user, t, base)
        config = load_user_config(user, base)
        household = config.household.model_copy(
            update={
                "dinners_per_week": max(1, min(7, dinners)),
                "budget_enabled": budget_enabled is not None,
                "budget_cents_weekly": max(20, min(2000, budget_dollars)) * 100,
            }
        )
        config = config.model_copy(update={"household": household})
        store = StateStore(user_dir(user, base))
        if standing.strip():
            from ..schemas.domain import StandingOrderLine

            config = config.model_copy(
                update={
                    "standing_orders": [
                        *config.standing_orders,
                        StandingOrderLine(raw=standing.strip(), reason="standing"),
                    ]
                }
            )
        save_user_config(user, config, base)
        if request.strip():
            store.append_learning(f"Household request ({date.today().isoformat()}): {request.strip()}")
        return RedirectResponse(f"/u/{user}?t={t}&saved=Preferences+saved", status_code=303)

    return app
