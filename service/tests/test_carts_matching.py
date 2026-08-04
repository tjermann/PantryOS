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
