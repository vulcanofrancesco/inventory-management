"""
Tests for the restocking endpoints:
GET  /api/restocking/recommendations
POST /api/restocking/orders
GET  /api/restocking/orders
"""
from datetime import date, timedelta

TREND_ORDER = {"increasing": 0, "stable": 1, "decreasing": 2}


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

    def test_negative_budget_rejected(self, client):
        response = client.get("/api/restocking/recommendations?budget=-5")
        assert response.status_code == 400


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
        expected = date.today() + timedelta(days=order["lead_time_days"])
        assert order["expected_delivery"] == expected.isoformat()

        listed = client.get("/api/restocking/orders").json()
        assert listed[0]["id"] == order["id"]  # newest first

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

    def test_ranks_have_no_gaps(self, client):
        items = get_recommendations(client, 5000)["items"]
        assert [i["priority_rank"] for i in items] == list(range(1, len(items) + 1))
