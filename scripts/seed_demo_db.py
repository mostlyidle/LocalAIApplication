#!/usr/bin/env python3
"""Seed a demo SQLite database with sample data for the SQL Agent.

Creates a realistic small business database with customers, products, orders,
and employees tables. This is the *target* database the SQL Agent queries —
not the application database.

Usage:
    cd backend
    uv run python ../scripts/seed_demo_db.py          # default: ./data/demo.db
    uv run python ../scripts/seed_demo_db.py my.db    # custom path
"""

from __future__ import annotations

import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

# ── Configuration ───────────────────────────────────────────────────────

DEFAULT_DB_PATH = (
    Path(__file__).resolve().parent.parent / "backend" / "data" / "demo.db"
)

CUSTOMERS = [
    ("Alice Johnson", "alice@example.com", "New York", "USA"),
    ("Bob Smith", "bob@example.com", "London", "UK"),
    ("Carlos Garcia", "carlos@example.com", "Madrid", "Spain"),
    ("Diana Müller", "diana@example.com", "Berlin", "Germany"),
    ("Eva Svensson", "eva@example.com", "Stockholm", "Sweden"),
    ("Frank Chen", "frank@example.com", "Shanghai", "China"),
    ("Grace Kim", "grace@example.com", "Seoul", "South Korea"),
    ("Hiro Tanaka", "hiro@example.com", "Tokyo", "Japan"),
    ("Isabella Rossi", "isabella@example.com", "Rome", "Italy"),
    ("Jamal Williams", "jamal@example.com", "Chicago", "USA"),
    ("Karen Thompson", "karen@example.com", "Toronto", "Canada"),
    ("Liam O'Brien", "liam@example.com", "Dublin", "Ireland"),
    ("Mia Anderson", "mia@example.com", "Sydney", "Australia"),
    ("Noah Patel", "noah@example.com", "Mumbai", "India"),
    ("Olivia Brown", "olivia@example.com", "San Francisco", "USA"),
]

PRODUCTS = [
    ("Widget Pro", "Electronics", 29.99, 150),
    ("Widget Lite", "Electronics", 14.99, 300),
    ("Gadget X", "Electronics", 49.99, 80),
    ("Office Chair Deluxe", "Furniture", 299.99, 25),
    ("Standing Desk", "Furniture", 449.99, 15),
    ("Monitor Arm", "Furniture", 79.99, 60),
    ("Notebook Premium", "Stationery", 12.99, 500),
    ("Pen Set Executive", "Stationery", 24.99, 200),
    ("Wireless Mouse", "Electronics", 34.99, 120),
    ("Mechanical Keyboard", "Electronics", 89.99, 75),
    ("USB-C Hub", "Electronics", 44.99, 90),
    ("Desk Lamp LED", "Furniture", 59.99, 45),
    ("Webcam HD", "Electronics", 69.99, 55),
    ("Noise-Cancel Headphones", "Electronics", 199.99, 40),
    ("Whiteboard Markers (12)", "Stationery", 8.99, 350),
]

EMPLOYEES = [
    ("Sarah Connor", "Engineering", "Senior Engineer", 120000),
    ("John Wick", "Sales", "Sales Manager", 95000),
    ("Neo Anderson", "Engineering", "Staff Engineer", 145000),
    ("Trinity Lee", "Engineering", "Engineer", 105000),
    ("Morpheus Brown", "Sales", "VP Sales", 150000),
    ("Ellen Ripley", "Operations", "Operations Manager", 90000),
    ("Tony Stark", "Engineering", "Director of Engineering", 170000),
    ("Natasha Romanoff", "Marketing", "Marketing Lead", 100000),
    ("Bruce Wayne", "Finance", "CFO", 180000),
    ("Clark Kent", "Marketing", "Content Specialist", 75000),
]

ORDER_STATUSES = ["pending", "shipped", "delivered", "cancelled"]


def create_schema(conn: sqlite3.Connection) -> None:
    """Create all tables."""
    conn.executescript("""
        DROP TABLE IF EXISTS order_items;
        DROP TABLE IF EXISTS orders;
        DROP TABLE IF EXISTS products;
        DROP TABLE IF EXISTS customers;
        DROP TABLE IF EXISTS employees;

        CREATE TABLE customers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            email       TEXT    NOT NULL UNIQUE,
            city        TEXT    NOT NULL,
            country     TEXT    NOT NULL,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE products (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            category    TEXT    NOT NULL,
            price       REAL    NOT NULL CHECK (price > 0),
            stock       INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0)
        );

        CREATE TABLE orders (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL REFERENCES customers(id),
            order_date  TEXT    NOT NULL,
            status      TEXT    NOT NULL DEFAULT 'pending',
            total       REAL    NOT NULL DEFAULT 0
        );

        CREATE TABLE order_items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id    INTEGER NOT NULL REFERENCES orders(id),
            product_id  INTEGER NOT NULL REFERENCES products(id),
            quantity    INTEGER NOT NULL CHECK (quantity > 0),
            unit_price  REAL    NOT NULL
        );

        CREATE TABLE employees (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            department  TEXT    NOT NULL,
            title       TEXT    NOT NULL,
            salary      REAL    NOT NULL,
            hire_date   TEXT    NOT NULL
        );

        -- Useful indexes
        CREATE INDEX idx_orders_customer ON orders(customer_id);
        CREATE INDEX idx_orders_date ON orders(order_date);
        CREATE INDEX idx_order_items_order ON order_items(order_id);
        CREATE INDEX idx_products_category ON products(category);
        CREATE INDEX idx_employees_department ON employees(department);
    """)


def seed_data(conn: sqlite3.Connection) -> dict[str, int]:
    """Insert demo data. Returns counts per table."""
    random.seed(42)  # reproducible
    counts: dict[str, int] = {}

    # Customers
    conn.executemany(
        "INSERT INTO customers (name, email, city, country) VALUES (?, ?, ?, ?)",
        CUSTOMERS,
    )
    counts["customers"] = len(CUSTOMERS)

    # Products
    conn.executemany(
        "INSERT INTO products (name, category, price, stock) VALUES (?, ?, ?, ?)",
        PRODUCTS,
    )
    counts["products"] = len(PRODUCTS)

    # Employees with random hire dates in last 5 years
    today = date.today()
    employee_rows = []
    for name, dept, title, salary in EMPLOYEES:
        hire_date = today - timedelta(days=random.randint(90, 1800))
        employee_rows.append((name, dept, title, salary, hire_date.isoformat()))
    conn.executemany(
        "INSERT INTO employees (name, department, title, salary, hire_date) VALUES (?, ?, ?, ?, ?)",
        employee_rows,
    )
    counts["employees"] = len(EMPLOYEES)

    # Orders — 60 orders spread over last 12 months
    num_orders = 60
    order_rows = []
    for _ in range(num_orders):
        customer_id = random.randint(1, len(CUSTOMERS))
        order_date = today - timedelta(days=random.randint(1, 365))
        status = random.choices(ORDER_STATUSES, weights=[10, 25, 55, 10])[0]
        order_rows.append((customer_id, order_date.isoformat(), status))

    conn.executemany(
        "INSERT INTO orders (customer_id, order_date, status, total) VALUES (?, ?, ?, 0)",
        order_rows,
    )
    counts["orders"] = num_orders

    # Order items — 1-4 items per order
    order_item_rows = []
    for order_id in range(1, num_orders + 1):
        num_items = random.randint(1, 4)
        product_ids = random.sample(range(1, len(PRODUCTS) + 1), num_items)
        for pid in product_ids:
            qty = random.randint(1, 5)
            price = PRODUCTS[pid - 1][2]  # use product price
            order_item_rows.append((order_id, pid, qty, price))

    conn.executemany(
        "INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
        order_item_rows,
    )
    counts["order_items"] = len(order_item_rows)

    # Update order totals
    conn.execute("""
        UPDATE orders SET total = (
            SELECT COALESCE(SUM(quantity * unit_price), 0)
            FROM order_items WHERE order_items.order_id = orders.id
        )
    """)

    conn.commit()
    return counts


def main() -> None:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Seeding demo database: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")

    create_schema(conn)
    counts = seed_data(conn)

    print("Done! Inserted:")
    for table, count in counts.items():
        print(f"  {table}: {count} rows")

    # Quick verification query
    cursor = conn.execute("""
        SELECT c.name, COUNT(o.id) as order_count, ROUND(SUM(o.total), 2) as total_spent
        FROM customers c
        LEFT JOIN orders o ON c.id = o.customer_id
        GROUP BY c.id
        ORDER BY total_spent DESC
        LIMIT 5
    """)
    print("\nTop 5 customers by spending:")
    for name, orders, total in cursor.fetchall():
        print(f"  {name}: {orders} orders, ${total:.2f}")

    conn.close()


if __name__ == "__main__":
    main()
