"""
Tests for the restocking endpoints:
GET  /api/restocking/recommendations
POST /api/restocking/orders
GET  /api/restocking/orders
"""
import itertools
from datetime import datetime, timedelta, timezone

import pytest

import main

TREND_ORDER = {"increasing": 0, "stable": 1, "decreasing": 2}


@pytest.fixture(autouse=True)
def reset_restock_orders():
    """Each test starts with no submitted orders and numbering from 1."""
    main.restock_orders.clear()
    main.restock_order_numbers = itertools.count(1)
    yield
    main.restock_orders.clear()
    main.restock_order_numbers = itertools.count(1)


def get_recommendations(client, budget=None):
    url = "/api/restocking/recommendations"
    if budget is not None:
        url += f"?budget={budget}"
    response = client.get(url)
    assert response.status_code == 200
    return response.json()


class TestRestockRecommendations:
    def test_without_budget_covers_everything(self, client):
        data = get_recommendations(client)
        assert data["budget"] == data["max_budget"]
        assert data["total_cost"] == data["max_budget"]
        assert len(data["items"]) > 0

    def test_zero_budget_recommends_nothing(self, client):
        data = get_recommendations(client, 0)
        assert data["items"] == []
        assert data["total_cost"] == 0

    def test_total_never_exceeds_budget(self, client):
        max_budget = get_recommendations(client)["max_budget"]
        for budget in [1, 50, 999.99, 5000, max_budget / 2, max_budget]:
            data = get_recommendations(client, budget)
            assert data["total_cost"] <= budget + 1e-6

    def test_line_totals_add_up(self, client):
        data = get_recommendations(client, 8000)
        for item in data["items"]:
            assert item["quantity"] > 0
            assert abs(item["line_total"] - item["quantity"] * item["unit_cost"]) < 0.01
        assert abs(sum(i["line_total"] for i in data["items"]) - data["total_cost"]) < 0.01

    def test_priority_order_by_trend(self, client):
        items = get_recommendations(client)["items"]
        ranks = [TREND_ORDER[i["trend"]] for i in items]
        assert ranks == sorted(ranks)
        assert [i["priority_rank"] for i in items] == sorted(i["priority_rank"] for i in items)

    def test_small_budget_goes_to_top_priority(self, client):
        top = get_recommendations(client)["items"][0]
        data = get_recommendations(client, top["unit_cost"] * 10)
        assert data["items"][0]["sku"] == top["sku"]
        assert data["items"][0]["quantity"] == 10

    @pytest.mark.parametrize("budget", ["-5", "inf", "-inf", "nan"])
    def test_invalid_budget_rejected(self, client, budget):
        response = client.get(f"/api/restocking/recommendations?budget={budget}")
        assert response.status_code == 422

    def test_budget_equal_to_cumulative_total(self, client):
        items = get_recommendations(client)["items"]
        exact = round(items[0]["line_total"] + items[1]["line_total"], 2)
        data = get_recommendations(client, exact)
        assert [i["sku"] for i in data["items"]] == [items[0]["sku"], items[1]["sku"]]
        assert data["total_cost"] == exact

    def test_ties_broken_by_bigger_shortfall(self, client):
        items = get_recommendations(client)["items"]
        for a, b in zip(items, items[1:]):
            if a["trend"] == b["trend"]:
                assert a["quantity"] >= b["quantity"]


class TestRestockOrders:
    def test_create_order_and_list_it(self, client):
        recs = get_recommendations(client, 3000)["items"]
        payload = {"items": [{"sku": i["sku"], "quantity": i["quantity"]} for i in recs]}

        response = client.post("/api/restocking/orders", json=payload)
        assert response.status_code == 201
        order = response.json()

        assert order["status"] == "Submitted"
        assert order["order_number"].startswith("RST-")
        assert abs(order["total_value"] - sum(i["line_total"] for i in recs)) < 0.01
        assert order["lead_time_days"] == max(i["lead_time_days"] for i in recs)
        today = datetime.now(timezone.utc).date()
        expected = today + timedelta(days=order["lead_time_days"])
        assert order["expected_delivery"] == expected.isoformat()

        listed = client.get("/api/restocking/orders").json()
        assert [o["id"] for o in listed] == [order["id"]]

    def test_orders_listed_newest_first(self, client):
        first = client.post("/api/restocking/orders",
                            json={"items": [{"sku": "WDG-001", "quantity": 1}]}).json()
        second = client.post("/api/restocking/orders",
                             json={"items": [{"sku": "WDG-001", "quantity": 1}]}).json()
        listed = client.get("/api/restocking/orders").json()
        assert [o["id"] for o in listed] == [second["id"], first["id"]]
        assert second["order_number"] == "RST-0002"

    def test_duplicate_skus_are_merged(self, client):
        response = client.post("/api/restocking/orders", json={"items": [
            {"sku": "WDG-001", "quantity": 2}, {"sku": "WDG-001", "quantity": 3}]})
        assert response.status_code == 201
        items = response.json()["items"]
        assert len(items) == 1 and items[0]["quantity"] == 5

    def test_quantity_above_need_rejected(self, client):
        need = {i["sku"]: i["quantity"] for i in get_recommendations(client)["items"]}
        response = client.post("/api/restocking/orders",
                               json={"items": [{"sku": "WDG-001", "quantity": need["WDG-001"] + 1}]})
        assert response.status_code == 400

    def test_same_plan_cannot_be_ordered_twice(self, client):
        recs = get_recommendations(client)["items"]
        payload = {"items": [{"sku": i["sku"], "quantity": i["quantity"]} for i in recs]}
        assert client.post("/api/restocking/orders", json=payload).status_code == 201
        assert client.post("/api/restocking/orders", json=payload).status_code == 400

    def test_ordered_units_reduce_recommendations(self, client):
        before = {i["sku"]: i["quantity"] for i in get_recommendations(client)["items"]}
        client.post("/api/restocking/orders", json={"items": [{"sku": "WDG-001", "quantity": 100}]})
        after = {i["sku"]: i["quantity"] for i in get_recommendations(client)["items"]}
        assert after["WDG-001"] == before["WDG-001"] - 100

    def test_unknown_sku_rejected(self, client):
        response = client.post("/api/restocking/orders",
                               json={"items": [{"sku": "NOPE-000", "quantity": 1}]})
        assert response.status_code == 400

    def test_zero_quantity_rejected(self, client):
        response = client.post("/api/restocking/orders",
                               json={"items": [{"sku": "WDG-001", "quantity": 0}]})
        assert response.status_code == 422

    def test_empty_order_rejected(self, client):
        response = client.post("/api/restocking/orders", json={"items": []})
        assert response.status_code == 422


class TestStrictPriority:
    def test_only_last_item_can_be_partial(self, client):
        full = {i["sku"]: i["quantity"] for i in get_recommendations(client)["items"]}
        for budget in [100, 5000, 9000, 15000, 20000]:
            items = get_recommendations(client, budget)["items"]
            # every item except the last one is fully covered
            for item in items[:-1]:
                assert item["quantity"] == full[item["sku"]]

    def test_partial_branch_is_exercised(self, client):
        # Guards against seed data changes making the partial case untested
        partials = []
        for budget in [100, 5000, 9000, 15000, 20000]:
            items = get_recommendations(client, budget)["items"]
            full = {i["sku"]: i["quantity"] for i in get_recommendations(client)["items"]}
            partials += [i for i in items if i["quantity"] < full[i["sku"]]]
        assert partials

    def test_ranks_have_no_gaps(self, client):
        items = get_recommendations(client, 5000)["items"]
        assert [i["priority_rank"] for i in items] == list(range(1, len(items) + 1))
