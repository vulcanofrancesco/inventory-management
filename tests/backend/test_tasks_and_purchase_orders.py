"""
Tests for the tasks and purchase-order endpoints the frontend already called
but the backend was missing.
"""
import itertools
from datetime import datetime, timedelta, timezone

import pytest

import main


@pytest.fixture(autouse=True)
def reset_state():
    """Each test starts with no API tasks and no purchase orders."""
    main.tasks.clear()
    main.task_ids = itertools.count(1)
    main.purchase_orders.clear()
    yield
    main.tasks.clear()
    main.purchase_orders.clear()


def future(days=10):
    return (datetime.now(timezone.utc).date() + timedelta(days=days)).isoformat()


class TestTasks:
    def test_empty_list(self, client):
        response = client.get("/api/tasks")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_toggle_delete(self, client):
        created = client.post("/api/tasks", json={
            "title": "  Check Tokyo stock  ", "priority": "high", "dueDate": "2026-12-01"})
        assert created.status_code == 201
        task = created.json()
        assert task["title"] == "Check Tokyo stock"
        assert task["status"] == "pending"
        assert task["id"].startswith("task-")  # never collides with mock ids 1-4

        toggled = client.patch(f"/api/tasks/{task['id']}").json()
        assert toggled["status"] == "completed"
        assert client.patch(f"/api/tasks/{task['id']}").json()["status"] == "pending"

        assert client.delete(f"/api/tasks/{task['id']}").status_code == 200
        assert client.get("/api/tasks").json() == []

    def test_newest_first(self, client):
        for title in ["first", "second"]:
            client.post("/api/tasks", json={"title": title, "dueDate": "2026-12-01"})
        assert [t["title"] for t in client.get("/api/tasks").json()] == ["second", "first"]

    @pytest.mark.parametrize("payload", [
        {"title": "", "dueDate": "2026-12-01"},
        {"title": "x", "dueDate": "not-a-date"},
        {"title": "x", "dueDate": "2026-12-01", "priority": "urgent"},
    ])
    def test_invalid_task_rejected(self, client, payload):
        assert client.post("/api/tasks", json=payload).status_code == 422

    def test_unknown_task_is_404(self, client):
        assert client.patch("/api/tasks/task-999").status_code == 404
        assert client.delete("/api/tasks/task-999").status_code == 404


def po_payload(**overrides):
    payload = {
        "backlog_item_id": "1",
        "supplier_name": "Acme Filters",
        "quantity": 350,
        "unit_cost": 12.9,
        "expected_delivery_date": future(),
        "notes": "Rush",
    }
    payload.update(overrides)
    return payload


class TestPurchaseOrders:
    def test_create_and_fetch(self, client):
        response = client.post("/api/purchase-orders", json=po_payload())
        assert response.status_code == 201
        po = response.json()
        assert po["status"] == "Pending"

        fetched = client.get("/api/purchase-orders/1")
        assert fetched.status_code == 200
        assert fetched.json()["id"] == po["id"]

    def test_backlog_shows_purchase_order(self, client):
        po = client.post("/api/purchase-orders", json=po_payload()).json()
        item = next(b for b in client.get("/api/backlog").json() if b["id"] == "1")
        assert item["has_purchase_order"] is True
        assert item["purchase_order_id"] == po["id"]

    def test_backlog_without_purchase_order(self, client):
        for item in client.get("/api/backlog").json():
            assert item["has_purchase_order"] is False
            assert item["purchase_order_id"] is None

    def test_one_purchase_order_per_item(self, client):
        assert client.post("/api/purchase-orders", json=po_payload()).status_code == 201
        assert client.post("/api/purchase-orders", json=po_payload()).status_code == 409

    def test_unknown_backlog_item(self, client):
        response = client.post("/api/purchase-orders", json=po_payload(backlog_item_id="999"))
        assert response.status_code == 404

    def test_missing_purchase_order_is_404(self, client):
        assert client.get("/api/purchase-orders/1").status_code == 404

    def test_past_delivery_date_rejected(self, client):
        response = client.post("/api/purchase-orders", json=po_payload(expected_delivery_date="2020-01-01"))
        assert response.status_code == 400

    @pytest.mark.parametrize("override", [
        {"quantity": 0}, {"unit_cost": 0}, {"supplier_name": ""},
    ])
    def test_invalid_purchase_order_rejected(self, client, override):
        assert client.post("/api/purchase-orders", json=po_payload(**override)).status_code == 422


def test_delivered_orders_have_delivery_date(client):
    for order in client.get("/api/orders").json():
        if order["status"] == "Delivered":
            assert order["actual_delivery"], order["order_number"]
