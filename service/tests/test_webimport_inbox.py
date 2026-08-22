"""URL-import JSON-LD extraction and reply-stripping tests — no network."""

import json

from mealplanner.emailer.inbox import strip_quoted_reply
from mealplanner.recipes.webimport import extract_jsonld_recipe, _iso_duration_min

JSONLD_PAGE = """<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
 {"@type":"WebSite","name":"Some Blog"},
 {"@type":"Recipe","name":"Lemony Chickpea Soup",
  "recipeYield":["4","4 servings"],
  "totalTime":"PT35M",
  "recipeIngredient":["2 tbsp olive oil","1 onion, diced","2 cans chickpeas"],
  "recipeInstructions":[
    {"@type":"HowToStep","text":"Saute the onion in olive oil."},
    {"@type":"HowToSection","itemListElement":[
      {"@type":"HowToStep","text":"Add chickpeas and simmer 20 minutes."}]}
  ]}]}
</script></head><body></body></html>"""


class TestJsonLdExtraction:
    def test_extracts_graph_recipe(self):
        data = extract_jsonld_recipe(JSONLD_PAGE)
        assert data["title"] == "Lemony Chickpea Soup"
        assert data["serves"] == 4
        assert data["total_min"] == 35
        assert data["ingredients"] == ["2 tbsp olive oil", "1 onion, diced", "2 cans chickpeas"]
        assert data["steps"] == [
            "Saute the onion in olive oil.",
            "Add chickpeas and simmer 20 minutes.",
        ]

    def test_non_recipe_page_returns_none(self):
        assert extract_jsonld_recipe("<html><body>hello</body></html>") is None
        page = '<script type="application/ld+json">{"@type":"Article"}</script>'
        assert extract_jsonld_recipe(page) is None

    def test_durations(self):
        assert _iso_duration_min("PT1H30M") == 90
        assert _iso_duration_min("PT45M") == 45
        assert _iso_duration_min("PT2H") == 120
        assert _iso_duration_min(None) is None
        assert _iso_duration_min("garbage") is None


class TestSourcePolicy:
    def _entry(self, slug, source, personal=False):
        from pathlib import Path

        from mealplanner.recipes.library import LibraryEntry
        from mealplanner.schemas.domain import Recipe

        recipe = Recipe(id=slug, title=slug, serves=4, protein="veg",
                        cuisine="x", seasons=["year_round"])
        return LibraryEntry(recipe=recipe, source=source,
                            markdown_path=Path("/nonexistent"), real_time_min=None,
                            personal=personal)

    def test_exclusive_keeps_configured_domains_and_personal(self):
        from mealplanner.recipes.merged import apply_source_policy

        entries = [
            self._entry("a", "https://cookieandkate.com/some-recipe/"),
            self._entry("b", "americastestkitchen.com"),
            self._entry("c", "https://www.halfbakedharvest.com/x/"),
            self._entry("d", "https://randomblog.net/y/", personal=True),
            self._entry("e", "PantryOS starter"),
        ]
        sources = ["https://cookieandkate.com/", "https://www.halfbakedharvest.com/"]
        kept = {e.recipe.id for e in apply_source_policy(entries, "exclusive", sources)}
        assert kept == {"a", "c", "d"}  # configured sites + hand-imported
        assert len(apply_source_policy(entries, "open", sources)) == 5


class TestSitemapParsing:
    def test_extracts_post_urls_and_skips_junk(self):
        from mealplanner.recipes.discover import SKIP_PATTERNS, _locs

        xml = """<urlset>
        <url><loc>https://cookieandkate.com/best-soup-recipe/</loc></url>
        <url><loc>https://cookieandkate.com/category/soups/</loc></url>
        <url><loc>https://cookieandkate.com/photo.jpg</loc></url>
        </urlset>"""
        locs = _locs(xml)
        assert len(locs) == 3
        kept = [u for u in locs if not SKIP_PATTERNS.search(u)]
        assert kept == ["https://cookieandkate.com/best-soup-recipe/"]


class TestReplyStripping:
    def test_keeps_own_words_drops_quote(self):
        body = (
            "Less spicy please! And Tuesday was great.\n"
            "\n"
            "On Tue, Aug 4, 2026 at 6:15 AM PantryOS <x@gmail.com> wrote:\n"
            "> THIS WEEK'S DINNERS\n"
            "> Wednesday: Shrimp...\n"
        )
        assert strip_quoted_reply(body) == "Less spicy please! And Tuesday was great."

    def test_drops_signature_and_quoted_lines(self):
        body = "More soups in fall.\n> quoted line\n--\nKaty\n"
        assert strip_quoted_reply(body) == "More soups in fall."

    def test_multiline_gmail_attribution(self):
        # Gmail wraps the attribution, so 'wrote:' lands on its own line.
        body = (
            "Can you pull all recipes from these 3 sources we like?\n"
            "\n"
            "https://cookieandkate.com/\n"
            "\n"
            "On Fri, Aug 7, 2026, 6:16 AM PantryOS <planner@gmail.com>\n"
            "wrote:\n"
            "> THIS WEEK'S DINNERS\n"
        )
        cleaned = strip_quoted_reply(body)
        assert "cookieandkate.com" in cleaned
        assert "PantryOS" not in cleaned and "wrote:" not in cleaned

    def test_phone_signature_dropped(self):
        body = "More soups please.\n\nSent from my iPhone\n"
        assert strip_quoted_reply(body) == "More soups please."

    def test_truncates_novels(self):
        assert len(strip_quoted_reply("x" * 9000)) == 1500


class TestReplyPicks:
    """A reply that chooses meals must do what the checkboxes do."""

    def _plan(self):
        return {
            "week": "2026-W35", "status": "proposed",
            "week_dates": ["2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27"],
            "select_dinners": 4, "select_lunches": 1, "selected": None,
            "entries": [
                {"recipe_id": f"opt-{i}", "date": "2026-08-24", "meal_type": "dinner",
                 "servings": 4, "rationale": ""} for i in range(7)
            ] + [
                {"recipe_id": "salad", "date": "2026-08-24", "meal_type": "lunch",
                 "servings": 4, "rationale": ""},
            ],
        }

    def _household(self):
        from fixtures_helpers import make_household

        h = make_household()
        h.dinners_per_week, h.lunches_per_week = 4, 1
        return h

    def test_picks_carryovers_and_counts_are_applied(self):
        from mealplanner.planning.reply_picks import ReplyPicks, apply_picks

        picks = ReplyPicks(
            is_about_picking=True, dinner_ids=["opt-3"], lunch_ids=["salad"],
            carry_over_ids=["last-week-rice"], dinner_count=3, lunch_count=1,
        )
        applied = apply_picks(picks, self._plan(), self._household(),
                              {"last-week-rice": "Fried Rice"})
        assert applied.dinners == ["opt-3"]
        assert applied.carried == ["last-week-rice"]
        assert applied.lunches == ["salad"]
        assert (applied.dinner_count, applied.lunch_count) == (3, 1)

    def test_ids_the_model_invents_are_discarded(self):
        from mealplanner.planning.reply_picks import ReplyPicks, apply_picks

        picks = ReplyPicks(is_about_picking=True,
                           dinner_ids=["opt-0", "not-a-real-dish"],
                           carry_over_ids=["also-invented"])
        applied = apply_picks(picks, self._plan(), self._household(), {})
        assert applied.dinners == ["opt-0"]
        assert applied.carried == []

    def test_a_dish_already_on_the_menu_is_not_treated_as_a_carryover(self):
        """Otherwise it would be marked as already bought and never shopped for."""
        from mealplanner.planning.reply_picks import ReplyPicks, apply_picks

        picks = ReplyPicks(is_about_picking=True, carry_over_ids=["opt-2"])
        applied = apply_picks(picks, self._plan(), self._household(),
                              {"opt-2": "On the menu"})
        assert applied.carried == []

    def test_counts_cannot_exceed_what_exists(self):
        from mealplanner.planning.reply_picks import ReplyPicks, apply_picks

        picks = ReplyPicks(is_about_picking=True, dinner_ids=["opt-1"],
                           dinner_count=99, lunch_count=99)
        applied = apply_picks(picks, self._plan(), self._household(), {})
        assert applied.dinner_count == 7 and applied.lunch_count == 1

    def test_a_plain_preference_changes_nothing(self):
        from mealplanner.planning.reply_picks import ReplyPicks, apply_picks

        picks = ReplyPicks(is_about_picking=False, other_notes="less spicy")
        applied = apply_picks(picks, self._plan(), self._household(), {})
        assert not applied.changed
