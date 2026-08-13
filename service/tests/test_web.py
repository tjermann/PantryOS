"""Web feedback UI tests: signed-link auth, one-click ratings, preference edits."""

import pytest
from fastapi.testclient import TestClient

from mealplanner.config import (
    EmailConfig,
    UserConfig,
    load_user_config,
    save_user_config,
    user_dir,
)
from mealplanner.schemas.domain import Household
from mealplanner.state.store import StateStore
from mealplanner.web.app import create_app, feedback_url, rating_url


@pytest.fixture()
def users_base(tmp_path):
    config = UserConfig(
        name="Test Family",
        email=EmailConfig(to=["fam@example.com"]),
        recipe_library=str(tmp_path / "library"),
        household=Household(
            id="test", name="Test Family",
            people=[{"id": "a", "name": "Alex"}],
        ),
    )
    save_user_config("test", config, tmp_path)
    store = StateStore(user_dir("test", tmp_path))
    store.save_plan("2026-W32", {
        "week": "2026-W32",
        "entries": [{"recipe_id": "coconut-curry", "date": "2026-08-04",
                     "servings": 4, "person_handling": []}],
    })
    return tmp_path


@pytest.fixture()
def client(users_base):
    return TestClient(create_app(users_base))


def test_page_requires_valid_token(client, users_base):
    assert client.get("/u/test").status_code == 403
    assert client.get("/u/test?t=forged").status_code == 403
    url = feedback_url("test", "", users_base)
    assert client.get(url).status_code == 200
    assert "Rate recent dinners" in client.get(url).text


def test_one_click_rating_records_state(client, users_base):
    url = rating_url("test", "", "coconut-curry", 5, users_base)
    response = client.get(url)
    assert response.status_code == 200
    state = StateStore(user_dir("test", users_base)).load_recipe_states()["coconut-curry"]
    assert state.ratings == [5]


def test_prefs_update_budget_and_learnings(client, users_base):
    url = feedback_url("test", "", users_base)
    token = url.split("t=")[1]
    response = client.post(
        "/prefs/test",
        data={"t": token, "dinners": "6", "budget_dollars": "180",
              "budget_enabled": "on", "request": "more fish please",
              "standing": "applesauce pouches"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    config = load_user_config("test", users_base)
    assert config.household.dinners_per_week == 6
    assert config.household.budget_enabled is True
    assert config.household.budget_cents_weekly == 18000
    assert any(s.raw == "applesauce pouches" for s in config.standing_orders)
    learnings = StateStore(user_dir("test", users_base)).load_learnings()
    assert "more fish please" in learnings


def test_grocery_toggle_round_trip(client, users_base):
    from mealplanner.config import user_dir

    url = feedback_url("test", "", users_base)
    token = url.split("t=")[1]
    store = StateStore(user_dir("test", users_base))
    assert store.load_exclusions("2026-W32") == []

    r = client.post("/grocery/test",
                    data={"t": token, "have": ["Jasmine rice", "Lemons"]},
                    follow_redirects=False)
    assert r.status_code == 303
    assert store.load_exclusions("2026-W32") == ["Jasmine rice", "Lemons"]

    # Unchecking everything = submit with no boxes ticked
    client.post("/grocery/test", data={"t": token}, follow_redirects=False)
    assert store.load_exclusions("2026-W32") == []

    assert client.post("/grocery/test", data={"t": "forged", "have": "x"},
                       follow_redirects=False).status_code == 403


def test_user_content_is_escaped(client, users_base):
    """A recipe title or note containing HTML must never execute."""
    from mealplanner.config import user_dir

    store = StateStore(user_dir("test", users_base))
    store.save_plan("2026-W33", {
        "week": "2026-W33", "status": "final",
        "entries": [{"recipe_id": "<img src=x onerror=alert(1)>", "date": "2026-08-11",
                     "servings": 4, "person_handling": []}],
    })
    store.save_staples(["<script>alert('staple')</script>"])
    body = client.get(feedback_url("test", "", users_base)).text
    # No live tags: the payload must appear as visible text, never as markup.
    assert "<script>" not in body
    assert "<img src=x" not in body
    assert "&lt;script&gt;" in body and "&lt;img" in body
    # And it must not have escaped an href/attribute boundary either.
    assert "src=x onerror=alert(1)>'" not in body


def test_saved_message_is_escaped(client, users_base):
    """The 'saved' query parameter is reflected — it must be escaped too."""
    url = feedback_url("test", "", users_base)
    body = client.get(f"{url}&saved=%3Cscript%3Ealert(1)%3C/script%3E").text
    assert "<script>alert(1)</script>" not in body


def test_expired_links_are_rejected(users_base, monkeypatch):
    import mealplanner.web.app as web

    url = feedback_url("test", "", users_base)
    monkeypatch.setattr(web, "TOKEN_MAX_AGE_S", -1)  # everything is now expired
    response = TestClient(web.create_app(users_base)).get(url)
    assert response.status_code == 403
    assert "expired" in response.text


def test_tokens_are_per_user(client, users_base):
    # A token minted for one user must not authorize another path.
    url = feedback_url("test", "", users_base)
    token = url.split("t=")[1]
    save_user_config(
        "other",
        UserConfig(
            name="Other", email=EmailConfig(to=["o@example.com"]),
            recipe_library="/nowhere",
            household=Household(id="other", name="Other", people=[{"id": "x", "name": "X"}]),
        ),
        users_base,
    )
    assert client.get(f"/u/other?t={token}").status_code == 403
