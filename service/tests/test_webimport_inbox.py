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

    def test_truncates_novels(self):
        assert len(strip_quoted_reply("x" * 9000)) == 1500
