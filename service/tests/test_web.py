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
