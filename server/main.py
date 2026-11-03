from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import itertools
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from pydantic import BaseModel, Field
from mock_data import inventory_items, orders, demand_forecasts, backlog_items, spending_summary, monthly_spending, category_spending, recent_transactions, purchase_orders

app = FastAPI(title="Factory Inventory Management System")

# Quarter mapping for date filtering
QUARTER_MAP = {
    'Q1-2025': ['2025-01', '2025-02', '2025-03'],
    'Q2-2025': ['2025-04', '2025-05', '2025-06'],
    'Q3-2025': ['2025-07', '2025-08', '2025-09'],
    'Q4-2025': ['2025-10', '2025-11', '2025-12']
}

def filter_by_month(items: list, month: Optional[str]) -> list:
    """Filter items by month/quarter based on order_date field"""
    if not month or month == 'all':
        return items

    if month.startswith('Q'):
        # Handle quarters
        if month in QUARTER_MAP:
            months = QUARTER_MAP[month]
            return [item for item in items if any(m in item.get('order_date', '') for m in months)]
    else:
        # Direct month match
        return [item for item in items if month in item.get('order_date', '')]

    return items

def apply_filters(items: list, warehouse: Optional[str] = None, category: Optional[str] = None,
                 status: Optional[str] = None) -> list:
    """Apply common filters to a list of items"""
    filtered = items

    if warehouse and warehouse != 'all':
        filtered = [item for item in filtered if item.get('warehouse') == warehouse]

    if category and category != 'all':
        filtered = [item for item in filtered if item.get('category', '').lower() == category.lower()]

    if status and status != 'all':
        filtered = [item for item in filtered if item.get('status', '').lower() == status.lower()]

    return filtered

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data models
class InventoryItem(BaseModel):
    id: str
    sku: str
    name: str
    category: str
    warehouse: str
    quantity_on_hand: int
    reorder_point: int
    unit_cost: float
    location: str
    last_updated: str

class Order(BaseModel):
    id: str
    order_number: str
    customer: str
    items: List[dict]
    status: str
    order_date: str
    expected_delivery: str
    total_value: float
    actual_delivery: Optional[str] = None
    warehouse: Optional[str] = None
    category: Optional[str] = None

class DemandForecast(BaseModel):
    id: str
    item_sku: str
    item_name: str
    current_demand: int
    forecasted_demand: int
    trend: str
    period: str
    unit_cost: float
    lead_time_days: int
    current_stock: int

class BacklogItem(BaseModel):
    id: str
    order_id: str
    item_sku: str
    item_name: str
    quantity_needed: int
    quantity_available: int
    days_delayed: int
    priority: str
    has_purchase_order: Optional[bool] = False

class PurchaseOrder(BaseModel):
    id: str
    backlog_item_id: str
    supplier_name: str
    quantity: int
    unit_cost: float
    expected_delivery_date: str
    status: str
    created_date: str
    notes: Optional[str] = None

class CreatePurchaseOrderRequest(BaseModel):
    backlog_item_id: str
    supplier_name: str
    quantity: int
    unit_cost: float
    expected_delivery_date: str
    notes: Optional[str] = None

class RestockRecommendation(BaseModel):
    sku: str
    name: str
    trend: str
    quantity: int
    unit_cost: float
    line_total: float
    lead_time_days: int
    priority_rank: int

class RestockRecommendationResponse(BaseModel):
    budget: float
    max_budget: float
    total_cost: float
    items: List[RestockRecommendation]

class RestockOrderLine(BaseModel):
    sku: str
    quantity: int = Field(gt=0)

class RestockOrderRequest(BaseModel):
    items: List[RestockOrderLine] = Field(min_length=1)

class RestockOrderItem(BaseModel):
    sku: str
    name: str
    quantity: int
    unit_cost: float
    line_total: float

class RestockOrder(BaseModel):
    id: str
    order_number: str
    items: List[RestockOrderItem]
    total_value: float
    status: str
    submitted_date: str
    lead_time_days: int
    expected_delivery: str

# Restocking orders live in memory only, like the rest of the app's data
restock_orders: List[dict] = []
# Separate counter so order numbers stay unique even if orders are ever removed
restock_order_numbers = itertools.count(1)

# API endpoints
@app.get("/")
def root():
    return {"message": "Factory Inventory Management System API", "version": "1.0.0"}

@app.get("/api/inventory", response_model=List[InventoryItem])
def get_inventory(
    warehouse: Optional[str] = None,
    category: Optional[str] = None
):
    """Get all inventory items with optional filtering"""
    return apply_filters(inventory_items, warehouse, category)

@app.get("/api/inventory/{item_id}", response_model=InventoryItem)
def get_inventory_item(item_id: str):
    """Get a specific inventory item"""
    item = next((item for item in inventory_items if item["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item

@app.get("/api/orders", response_model=List[Order])
def get_orders(
    warehouse: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None
):
    """Get all orders with optional filtering"""
    filtered_orders = apply_filters(orders, warehouse, category, status)
    filtered_orders = filter_by_month(filtered_orders, month)
    return filtered_orders

@app.get("/api/orders/{order_id}", response_model=Order)
def get_order(order_id: str):
    """Get a specific order"""
    order = next((order for order in orders if order["id"] == order_id), None)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@app.get("/api/demand", response_model=List[DemandForecast])
def get_demand_forecasts():
    """Get demand forecasts"""
    return demand_forecasts

@app.get("/api/backlog", response_model=List[BacklogItem])
def get_backlog():
    """Get backlog items with purchase order status"""
    # Add has_purchase_order flag to each backlog item
    result = []
    for item in backlog_items:
        item_dict = dict(item)
        # Check if this backlog item has a purchase order
        has_po = any(po["backlog_item_id"] == item["id"] for po in purchase_orders)
        item_dict["has_purchase_order"] = has_po
        result.append(item_dict)
    return result

@app.get("/api/dashboard/summary")
def get_dashboard_summary(
    warehouse: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None
):
    """Get summary statistics for dashboard with optional filtering"""
    # Filter inventory
    filtered_inventory = apply_filters(inventory_items, warehouse, category)

    # Filter orders
    filtered_orders = apply_filters(orders, warehouse, category, status)
    filtered_orders = filter_by_month(filtered_orders, month)

    total_inventory_value = sum(item["quantity_on_hand"] * item["unit_cost"] for item in filtered_inventory)
    low_stock_items = len([item for item in filtered_inventory if item["quantity_on_hand"] <= item["reorder_point"]])
    pending_orders = len([order for order in filtered_orders if order["status"] in ["Processing", "Backordered"]])
    total_backlog_items = len(backlog_items)

    return {
        "total_inventory_value": round(total_inventory_value, 2),
        "low_stock_items": low_stock_items,
        "pending_orders": pending_orders,
        "total_backlog_items": total_backlog_items,
        "total_orders_value": sum(order["total_value"] for order in filtered_orders)
    }

@app.get("/api/spending/summary")
def get_spending_summary():
    """Get spending summary statistics"""
    return spending_summary

@app.get("/api/spending/monthly")
def get_monthly_spending():
    """Get monthly spending breakdown"""
    return monthly_spending

@app.get("/api/spending/categories")
def get_category_spending():
    """Get spending by category"""
    return category_spending

@app.get("/api/spending/transactions")
def get_recent_transactions():
    """Get recent transactions"""
    return recent_transactions

@app.get("/api/reports/quarterly")
def get_quarterly_reports(
    warehouse: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None
):
    """Get quarterly performance reports with optional filtering"""
    filtered_orders = apply_filters(orders, warehouse, category, status)
    filtered_orders = filter_by_month(filtered_orders, month)

    # Calculate quarterly statistics from orders
    quarters = {}

    for order in filtered_orders:
        order_date = order.get('order_date', '')
        # Determine quarter
        if '2025-01' in order_date or '2025-02' in order_date or '2025-03' in order_date:
            quarter = 'Q1-2025'
        elif '2025-04' in order_date or '2025-05' in order_date or '2025-06' in order_date:
            quarter = 'Q2-2025'
        elif '2025-07' in order_date or '2025-08' in order_date or '2025-09' in order_date:
            quarter = 'Q3-2025'
        elif '2025-10' in order_date or '2025-11' in order_date or '2025-12' in order_date:
            quarter = 'Q4-2025'
        else:
            continue

        if quarter not in quarters:
            quarters[quarter] = {
                'quarter': quarter,
                'total_orders': 0,
                'total_revenue': 0,
                'delivered_orders': 0,
                'avg_order_value': 0
            }

        quarters[quarter]['total_orders'] += 1
        quarters[quarter]['total_revenue'] += order.get('total_value', 0)
        if order.get('status') == 'Delivered':
            quarters[quarter]['delivered_orders'] += 1

    # Calculate averages and fulfillment rate
    result = []
    for q, data in quarters.items():
        if data['total_orders'] > 0:
            data['avg_order_value'] = round(data['total_revenue'] / data['total_orders'], 2)
            data['fulfillment_rate'] = round((data['delivered_orders'] / data['total_orders']) * 100, 1)
        result.append(data)

    # Sort by quarter
    result.sort(key=lambda x: x['quarter'])
    return result

@app.get("/api/reports/monthly-trends")
def get_monthly_trends(
    warehouse: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None
):
    """Get month-over-month trends with optional filtering"""
    filtered_orders = apply_filters(orders, warehouse, category, status)
    filtered_orders = filter_by_month(filtered_orders, month)

    months = {}

    for order in filtered_orders:
        order_date = order.get('order_date', '')
        if not order_date:
            continue

        # Extract month (format: YYYY-MM-DD)
        month = order_date[:7]  # Gets YYYY-MM

        if month not in months:
            months[month] = {
                'month': month,
                'order_count': 0,
                'revenue': 0,
                'delivered_count': 0
            }

        months[month]['order_count'] += 1
        months[month]['revenue'] += order.get('total_value', 0)
        if order.get('status') == 'Delivered':
            months[month]['delivered_count'] += 1

    # Convert to list and sort
    result = list(months.values())
    result.sort(key=lambda x: x['month'])
    return result

TREND_PRIORITY = {"increasing": 0, "stable": 1, "decreasing": 2}

def get_quantities_on_order() -> dict:
    """Units per SKU already covered by submitted restocking orders."""
    totals: dict = {}
    for order in restock_orders:
        for item in order["items"]:
            totals[item["sku"]] = totals.get(item["sku"], 0) + item["quantity"]
    return totals

def get_restock_needs() -> list:
    """Forecast items that need restocking, in priority order.

    Need = forecasted demand not covered by current stock or by restocking
    orders already submitted. Items with growing demand come first, then
    stable, then decreasing; within the same trend the bigger shortfall wins.
    """
    on_order = get_quantities_on_order()
    needs = []
    for forecast in demand_forecasts:
        # Free items can't be budgeted for, so they are never recommended
        if forecast["unit_cost"] <= 0:
            continue
        shortfall = (forecast["forecasted_demand"] - forecast["current_stock"]
                     - on_order.get(forecast["item_sku"], 0))
        if shortfall > 0:
            needs.append({**forecast, "shortfall": shortfall})
    needs.sort(key=lambda f: (TREND_PRIORITY.get(f["trend"], 3), -f["shortfall"]))
    return needs

@app.get("/api/restocking/recommendations", response_model=RestockRecommendationResponse)
def get_restock_recommendations(
    # ge/allow_inf_nan reject negative, inf and nan budgets with a 422
    budget: Optional[float] = Query(None, ge=0, allow_inf_nan=False)
):
    """Recommend what to restock within a budget, filled in priority order."""
    needs = get_restock_needs()
    max_budget = round(sum(n["shortfall"] * n["unit_cost"] for n in needs), 2)
    if budget is None:
        budget = max_budget

    # Work in cents so float rounding can't push the total over budget
    remaining_cents = int(round(budget * 100))
    items = []
    for rank, need in enumerate(needs, start=1):
        unit_cents = int(round(need["unit_cost"] * 100))
        # Strict priority: the first item that doesn't fully fit gets as many
        # whole units as the budget allows, and filling stops there. Lower
        # priority items never jump ahead just because they are cheap.
        quantity = min(need["shortfall"], remaining_cents // unit_cents)
        partial = quantity < need["shortfall"]
        if quantity <= 0:
            break
        remaining_cents -= quantity * unit_cents
        items.append({
            "sku": need["item_sku"],
            "name": need["item_name"],
            "trend": need["trend"],
            "quantity": quantity,
            "unit_cost": need["unit_cost"],
            "line_total": round(quantity * unit_cents / 100, 2),
            "lead_time_days": need["lead_time_days"],
            "priority_rank": rank,
        })
        if partial:
            break

    return {
        "budget": round(budget, 2),
        "max_budget": max_budget,
        "total_cost": round(sum(i["line_total"] for i in items), 2),
        "items": items,
    }

@app.post("/api/restocking/orders", response_model=RestockOrder, status_code=201)
def create_restock_order(request: RestockOrderRequest):
    """Submit a restocking order; priced from the forecast data.

    Quantities can't exceed what is still needed, so the same plan can't be
    ordered twice and the client can't order arbitrary amounts.
    """
    forecasts_by_sku = {f["item_sku"]: f for f in demand_forecasts}
    shortfall_by_sku = {n["item_sku"]: n["shortfall"] for n in get_restock_needs()}

    # Merge repeated SKUs into one line, keeping first-seen order
    quantities: dict = {}
    for line in request.items:
        if line.sku not in forecasts_by_sku:
            raise HTTPException(status_code=400, detail=f"Unknown SKU {line.sku}")
        quantities[line.sku] = quantities.get(line.sku, 0) + line.quantity

    lines = []
    for sku, quantity in quantities.items():
        forecast = forecasts_by_sku[sku]
        still_needed = shortfall_by_sku.get(sku, 0)
        if quantity > still_needed:
            raise HTTPException(
                status_code=400,
                detail=f"{sku}: requested {quantity} but only {still_needed} still needed",
            )
        lines.append({
            "sku": sku,
            "name": forecast["item_name"],
            "quantity": quantity,
            "unit_cost": forecast["unit_cost"],
            "line_total": round(quantity * forecast["unit_cost"], 2),
            "lead_time_days": forecast["lead_time_days"],
        })

    # The order arrives when its slowest item does
    lead_time = max(l["lead_time_days"] for l in lines)
    # UTC so the dates don't depend on the server's local time zone
    today = datetime.now(timezone.utc).date()
    number = next(restock_order_numbers)
    order = {
        "id": str(number),
        "order_number": f"RST-{number:04d}",
        "items": [{k: v for k, v in l.items() if k != "lead_time_days"} for l in lines],
        "total_value": round(sum(l["line_total"] for l in lines), 2),
        "status": "Submitted",
        "submitted_date": today.isoformat(),
        "lead_time_days": lead_time,
        "expected_delivery": (today + timedelta(days=lead_time)).isoformat(),
    }
    restock_orders.append(order)
    return order

@app.get("/api/restocking/orders", response_model=List[RestockOrder])
def get_restock_orders():
    """Submitted restocking orders, newest first."""
    return list(reversed(restock_orders))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
