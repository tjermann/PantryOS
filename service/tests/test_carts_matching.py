"""Deterministic cart-matching logic (no browser)."""

from mealplanner.carts.base import CartReport, LineResult
from mealplanner.carts.selector_driver import clean_query, load_selector_pack, score_match


class TestCleanQuery:
    def test_strips_quantities_units_and_prep(self):
        assert clean_query("1/4 cup cilantro, chopped") == "cilantro"
        assert clean_query("1 avocado, cut into 1/2-inch pieces") == "avocado"
        assert clean_query("4 salmon fillets, skin-on") == "salmon fillets"
        assert clean_query("1 1/2 lb extra-large shrimp (21-25), peeled and deveined") \
            == "extra-large shrimp"
        assert clean_query("6 scallions, whites/greens separated, sliced thin") == "scallions"
        assert clean_query("2 cups fresh basil leaves") == "fresh basil leaves"

    def test_plain_names_pass_through(self):
        assert clean_query("Jasmine rice") == "Jasmine rice"
        assert clean_query("frozen blueberries") == "frozen blueberries"


class TestScoreMatch:
    def test_exact_and_partial(self):
        assert score_match("chicken thighs", "Chicken Thighs, Boneless 1lb") == 1.0
        assert score_match("coconut milk", "Thai Kitchen Coconut Milk 13.5oz") == 1.0
        assert 0 < score_match("jasmine rice", "Rice Krispies Cereal") < 1

    def test_stopwords_ignored(self):
        assert score_match("fresh organic cilantro", "Cilantro Bunch") == 1.0

    def test_no_match(self):
        assert score_match("saffron threads", "Chocolate Chip Cookies") == 0.0

    def test_plural_singular_folding(self):
        assert score_match("bananas", "Banana Conventional, 1 Each") == 1.0
        assert score_match("chicken thighs", "Boneless Chicken Thigh Pack") == 1.0
        assert score_match("cherry tomatoes", "Cherry Tomato, 1 Pint") == 1.0


class TestFormMatching:
    def test_frozen_request_requires_frozen_product(self):
        from mealplanner.carts.selector_driver import form_score

        assert form_score("frozen blueberries", "365 Organic Frozen Blueberries") == 1.0
        assert form_score("frozen blueberries", "Fresh Blueberries, 1 Pint") < 0.3

    def test_fresh_herbs_never_match_dried(self):
        from mealplanner.carts.selector_driver import form_score

        assert form_score("chives", "Fresh Chives, 0.75 oz") == 1.0
        assert form_score("chives", "McCormick Dried Chives") < 0.2
        assert form_score("basil", "Ground Dried Basil Leaves") < 0.2
        # explicitly asking for dried is honored
        assert form_score("dried oregano", "Dried Oregano Leaves") == 1.0

    def test_non_herb_forms_penalized_gently(self):
        from mealplanner.carts.selector_driver import form_score

        assert 0.5 < form_score("black beans", "Canned Black Beans") < 1.0


class TestProductMemory:
    def test_remembered_product_wins(self, tmp_path):
        from mealplanner.state.store import StateStore

        store = StateStore(tmp_path)
        store.record_cart_outcomes("amazon", [
            {"display_name": "frozen waffles", "status": "added",
             "product_title": "Vans Gluten Free Waffles, 6 ct"},
            {"display_name": "Chicken thighs", "status": "not_found"},
        ])
        prefs = store.preferred_products()
        assert prefs["frozen waffle"] == "Vans Gluten Free Waffles, 6 ct"
        assert store.problem_items(min_failures=1) == ["Chicken thighs"]

        # a later success clears the problem flag
        store.record_cart_outcomes("amazon", [
            {"display_name": "Chicken thighs", "status": "added",
             "product_title": "Organic Chicken Thighs"},
        ])
        assert store.problem_items(min_failures=1) == []


class TestSelectorPacks:
    def test_amazon_pack_has_all_slots(self):
        pack = load_selector_pack("amazon_fresh")
        for slot in ("home_url", "login_url", "cart_url", "signin_marker",
                     "search_input", "result_card", "result_title", "add_button"):
            assert pack.get(slot), f"missing slot {slot}"

    def test_unknown_pack_falls_back_to_generic(self):
        pack = load_selector_pack("no-such-store")
        assert pack.get("search_input")

    def test_user_override_wins(self, tmp_path):
        (tmp_path / "mystore.yaml").write_text("home_url: https://example.com\n")
        pack = load_selector_pack("mystore", tmp_path)
        assert pack["home_url"] == "https://example.com"


def test_cart_report_summary():
    report = CartReport(store_id="s", session="ok", results=[
        LineResult("a", "added"), LineResult("b", "added"),
        LineResult("c", "substituted", product_title="alt"),
        LineResult("d", "not_found"),
    ])
    assert report.added == 2
    assert report.not_found == ["d"]
    assert report.summary() == "2 added, 1 substituted, 1 not found"

    expired = CartReport(store_id="s", session="expired")
    assert "expired" in expired.summary()
