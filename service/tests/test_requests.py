"""Dishes the household asks for ahead of the proposal ('we want these three —
give us options for two more')."""

from datetime import date

from fixtures_helpers import ITEMS, ing, make_household, make_recipe
from mealplanner.schemas.plan import PlanEntryProposal, PlanProposal

FRIDAY = date(2026, 10, 16)  # proposal day; cart loads Sunday, nights start Monday
ASKED = ["bowl", "pasta-salad", "enchilada-skillet"]


def _recipes():
    return {
        r: make_recipe(r, ingredients=[ing("chicken-thigh", "1 lb chicken", 1, "lb")])
        for r in [*ASKED, "opt1", "opt2", "opt3", "opt4", "lunch1"]
    }


def _option(recipe_id, meal_type="dinner"):
    return PlanEntryProposal(recipe_id=recipe_id, date="2026-10-19",
                             meal_type=meal_type, servings=4, rationale="option")


def _setup(tmp_path, monkeypatch, asked=ASKED, dinners=5):
    """A household with 7-for-4 shortlists and a planner stub that records what
    it was asked for."""
    from mealplanner.config import EmailConfig, UserConfig, save_user_config, user_dir
    from mealplanner.jobs import propose
    from mealplanner.llm.planner import LlmUsage, PlanRunResult
    from mealplanner.planning.validate import ValidationResult
    from mealplanner.schemas.domain import Household
    from mealplanner.state.store import StateStore

    config = UserConfig(
        name="T", email=EmailConfig(to=["a@b.c"]),
        recipe_library=str(tmp_path / "lib"), proposal_day="friday",
        planning_day="sunday",
        household=Household(id="t", name="T", dinners_per_week=4, dinner_options=7,
                            lunches_per_week=1, lunch_options=2),
    )
    save_user_config("t", config, tmp_path)
    store = StateStore(user_dir("t", tmp_path))
    store.set_requests("2026-W43", asked, dinners)

    calls = []

    def fake_generate(user, config, store, week_dates, base=None, **kw):
        calls.append({"slots": len(week_dates), **kw})
        options = [_option(f"opt{i + 1}") for i in range(len(week_dates))]
        result = PlanRunResult(
            proposal=PlanProposal(entries=[*options, _option("lunch1", "lunch")]),
            validation=ValidationResult(ok=True, errors=[], warnings=[]),
            dropped_recipe_ids=[], usage=LlmUsage(0, 0, 0, 1),
            prompt_version="v1", model="m",
        )
        return result, _recipes(), {}

    monkeypatch.setattr(propose, "generate_plan", fake_generate)
    # Never let a test reach the household's real SMTP account.
    sent = []
    monkeypatch.setattr(propose, "send_email", lambda **kw: sent.append(kw))
    monkeypatch.setattr("mealplanner.emailer.sender.send_email",
                        lambda **kw: sent.append(kw))
    monkeypatch.setattr("mealplanner.jobs.review.run_review", lambda *a, **k: 0)

    def no_network(*a, **k):
        raise AssertionError("test tried to open a real SMTP connection")

    monkeypatch.setattr("smtplib.SMTP_SSL", no_network)
    return store, calls


class TestProposeWithRequests:
    def test_requested_dishes_lead_and_are_preselected(self, tmp_path, monkeypatch):
        from mealplanner.jobs.propose import run_propose

        store, calls = _setup(tmp_path, monkeypatch)
        run_propose("t", base=tmp_path, today=FRIDAY, force=True, dry_run=False)
        plan = store.load_plan("2026-W43")
        assert [e["recipe_id"] for e in plan["entries"][:3]] == ASKED
        assert plan["selected"] == ASKED
        assert plan["requested"] == ASKED
        assert plan["select_dinners"] == 5
        assert len(plan["week_dates"]) == 5
        # The planner fills only the open nights: 2 picks, 7:4 ratio -> 4 options.
        assert calls[0]["requested"] == ASKED
        assert calls[0]["pick_dinners"] == 2
        assert calls[0]["slots"] == 4

    def test_unanswered_week_is_the_requests_plus_top_options(self, tmp_path, monkeypatch):
        from mealplanner.jobs.propose import run_propose
        from mealplanner.planning.selection import resolve_selection

        store, _ = _setup(tmp_path, monkeypatch)
        run_propose("t", base=tmp_path, today=FRIDAY, force=True, dry_run=False)
        plan = store.load_plan("2026-W43")
        menu = resolve_selection(plan, make_household(dinners_per_week=4))
        dinners = [e["recipe_id"] for e in menu if e["meal_type"] == "dinner"]
        assert dinners == [*ASKED, "opt1", "opt2"]

    def test_email_marks_requests_as_chosen(self, tmp_path, monkeypatch, capsys):
        from mealplanner.jobs.propose import run_propose

        _setup(tmp_path, monkeypatch)
        run_propose("t", base=tmp_path, today=FRIDAY, force=True, dry_run=True)
        out = capsys.readouterr().out
        assert "3 you chose, plus pick 2 of 4 options" in out
        assert "Chosen: bowl [your pick]" in out
        assert "Option 1: opt1 [default]" in out
        assert "Option 3: opt3 [default]" not in out

    def test_no_requests_is_a_normal_week(self, tmp_path, monkeypatch):
        from mealplanner.jobs.propose import run_propose

        store, calls = _setup(tmp_path, monkeypatch, asked=[])
        run_propose("t", base=tmp_path, today=FRIDAY, force=True, dry_run=False)
        plan = store.load_plan("2026-W43")
        assert plan["selected"] is None and plan["requested"] == []
        assert plan["select_dinners"] == 4
        assert calls[0]["slots"] == 7

    def test_iterate_revises_when_only_requests_are_selected(self, tmp_path, monkeypatch):
        from mealplanner.jobs.propose import run_iterate, run_propose

        store, calls = _setup(tmp_path, monkeypatch)
        run_propose("t", base=tmp_path, today=FRIDAY, force=True, dry_run=False)
        store.append_learning("less chicken please")
        run_iterate("t", base=tmp_path, today=FRIDAY, dry_run=False)
        plan = store.load_plan("2026-W43")
        assert len(calls) == 2  # re-planned
        assert plan["iteration"] == 2
        assert plan["selected"] == ASKED


class TestRequestedEntries:
    def test_allergen_backstop_still_applies(self):
        from mealplanner.jobs.common import requested_entries

        household = make_household(
            restrictions=[{"person_id": "p2", "allergen_class": "dairy",
                           "severity": "allergy"}]
        )
        recipes = {
            "creamy": make_recipe("creamy", ingredients=[
                ing("heavy-cream", "1 cup cream", 1, "cup", 3)]),
            "safe": make_recipe("safe", ingredients=[
                ing("chicken-thigh", "1 lb chicken", 1, "lb")]),
        }
        entries, refused = requested_entries(
            ["creamy", "safe", "missing"], recipes, household,
            [date(2026, 10, 19), date(2026, 10, 20)],
        )
        assert [e.recipe_id for e in entries] == ["safe"]
        assert len(refused) == 2

    def test_planner_is_told_what_is_already_chosen(self):
        from test_planner import FakeClient, entry

        from mealplanner.llm.planner import propose_plan

        safe = make_recipe("safe", ingredients=[ing("chicken-thigh", "1 lb chicken", 1, "lb")])
        bowl = make_recipe("Harvest Bowl", protein="chicken", cuisine="american")
        client = FakeClient([PlanProposal(entries=[entry("safe")])])
        propose_plan(client, model="m", candidates=[safe], states={}, items=ITEMS,
                     household=make_household(), week_dates=[date(2026, 10, 19)],
                     already_chosen=[bowl])
        prompt = client.calls[0]["messages"][0]["content"]
        assert "[ALREADY CHOSEN]" in prompt and "Harvest Bowl (chicken, american)" in prompt


class TestReplyKeepsRequests:
    def test_naming_two_options_adds_to_the_requests(self, tmp_path, monkeypatch):
        """'We'll take options 2 and 4' means two MORE, not a two-dinner week."""
        from mealplanner.config import load_user_config
        from mealplanner.jobs import reply
        from mealplanner.jobs.propose import run_propose
        from mealplanner.planning.reply_picks import ReplyPicks

        store, _ = _setup(tmp_path, monkeypatch)
        run_propose("t", base=tmp_path, today=FRIDAY, force=True, dry_run=False)
        monkeypatch.setattr(reply, "interpret_reply", lambda *a, **k: ReplyPicks(
            is_about_picking=True, dinner_ids=["opt2", "opt4"]))
        monkeypatch.setattr("mealplanner.llm.client.client_for_user", lambda c: None)
        reply.apply_reply("t", load_user_config("t", tmp_path), "2 and 4 please",
                          base=tmp_path)
        plan = store.load_plan("2026-W43")
        assert plan["selected"][:5] == [*ASKED, "opt2", "opt4"]
        assert plan["select_dinners"] == 5


class TestEarlyExecution:
    def test_scheduled_run_skips_a_week_already_executed(self, tmp_path, capsys):
        """Cart loaded early on Friday: Sunday's cron must not plan and shop again."""
        from mealplanner.config import EmailConfig, UserConfig, save_user_config, user_dir
        from mealplanner.jobs.weekly import run_weekly
        from mealplanner.schemas.domain import Household
        from mealplanner.state.store import StateStore

        config = UserConfig(
            name="T", email=EmailConfig(to=["a@b.c"]),
            recipe_library=str(tmp_path / "lib"), proposal_day="friday",
            planning_day="sunday",
            household=Household(id="t", name="T", dinners_per_week=4),
        )
        save_user_config("t", config, tmp_path)
        StateStore(user_dir("t", tmp_path)).save_plan(
            "2026-W43", {"week": "2026-W43", "status": "final", "entries": []})
        # No LLM or library is stubbed: planning fresh would blow up.
        assert run_weekly("t", base=tmp_path, today=date(2026, 10, 18)) == 0
        assert "already executed" in capsys.readouterr().out
