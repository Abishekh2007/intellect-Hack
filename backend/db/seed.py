"""Seed a demo e-commerce SQLite database.

The database is created once at startup (in a *writable* temporary
connection) and thereafter accessed read-only. Seed data is deterministic
so the demo behaves identically every run and tests can rely on it.
"""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    customer_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT,
    city TEXT,
    signup_date TEXT
);
CREATE TABLE IF NOT EXISTS products (
    product_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT,
    price REAL NOT NULL,
    stock INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    order_date TEXT NOT NULL,
    status TEXT DEFAULT 'completed',
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);
CREATE TABLE IF NOT EXISTS order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(order_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);
CREATE TABLE IF NOT EXISTS inventory (
    inventory_id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL,
    warehouse TEXT,
    stock_level INTEGER NOT NULL,
    updated_at TEXT,
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);
"""


def seed_database(db_path: Path) -> None:
    """Create schema and insert a deterministic demo dataset."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        cur = conn.execute("SELECT COUNT(*) AS c FROM customers").fetchone()
        if cur and cur[0] > 0:
            return  # already seeded

        customers = [
            (1, "Aarav Sharma", "aarav@example.com", "Chennai", "2024-01-15"),
            (2, "Meera Nair", "meera@example.com", "Mumbai", "2024-02-10"),
            (3, "Kabir Singh", "kabir@example.com", "Delhi", "2024-03-05"),
            (4, "Ananya Iyer", "ananya@example.com", "Bengaluru", "2024-03-22"),
            (5, "Rohan Gupta", "rohan@example.com", "Chennai", "2024-04-18"),
            (6, "Priya Patel", "priya@example.com", "Ahmedabad", "2024-05-02"),
            (7, "Vikram Rao", "vikram@example.com", "Hyderabad", "2024-06-11"),
        ]
        conn.executemany(
            "INSERT INTO customers (customer_id, name, email, city, signup_date) VALUES (?,?,?,?,?)",
            customers,
        )

        products = [
            (1, "Wireless Mouse", "Electronics", 899.0, 150),
            (2, "Mechanical Keyboard", "Electronics", 2499.0, 80),
            (3, "USB-C Cable", "Accessories", 349.0, 500),
            (4, "Laptop Stand", "Accessories", 1299.0, 120),
            (5, "Monitor 24in", "Electronics", 12999.0, 45),
            (6, "Desk Lamp", "Home", 799.0, 90),
            (7, "Noise Cancelling Headphones", "Electronics", 7999.0, 60),
        ]
        conn.executemany(
            "INSERT INTO products (product_id, name, category, price, stock) VALUES (?,?,?,?,?)",
            products,
        )

        orders = [
            (1, 1, "2024-05-01", "completed"),
            (2, 2, "2024-05-03", "completed"),
            (3, 3, "2024-05-07", "pending"),
            (4, 1, "2024-05-12", "completed"),
            (5, 4, "2024-05-15", "completed"),
            (6, 2, "2024-05-19", "completed"),
            (7, 5, "2024-05-21", "cancelled"),
            (8, 6, "2024-05-25", "completed"),
            (9, 3, "2024-05-28", "completed"),
            (10, 7, "2024-06-02", "completed"),
            (11, 5, "2024-06-06", "completed"),
            (12, 1, "2024-06-09", "completed"),
            (13, 4, "2024-06-12", "pending"),
            (14, 2, "2024-06-15", "completed"),
            (15, 6, "2024-06-18", "completed"),
        ]
        conn.executemany(
            "INSERT INTO orders (order_id, customer_id, order_date, status) VALUES (?,?,?,?)",
            orders,
        )

        items = [
            (1, 1, 1, 2, 899.0),
            (2, 1, 2, 1, 2499.0),
            (3, 2, 3, 5, 349.0),
            (4, 3, 5, 1, 12999.0),
            (5, 4, 4, 1, 1299.0),
            (6, 5, 7, 1, 7999.0),
            (7, 6, 6, 2, 799.0),
            (8, 7, 3, 2, 349.0),
            (9, 8, 1, 1, 899.0),
            (10, 9, 2, 1, 2499.0),
            (11, 10, 5, 2, 12999.0),
            (12, 11, 7, 1, 7999.0),
            (13, 12, 3, 3, 349.0),
            (14, 13, 6, 1, 799.0),
            (15, 14, 1, 1, 899.0),
            (16, 15, 4, 1, 1299.0),
        ]
        conn.executemany(
            "INSERT INTO order_items (order_item_id, order_id, product_id, quantity, unit_price) VALUES (?,?,?,?,?)",
            items,
        )

        inventory = [
            (1, 1, "Chennai WH", 150, "2024-06-20"),
            (2, 2, "Chennai WH", 80, "2024-06-20"),
            (3, 3, "Mumbai WH", 500, "2024-06-20"),
            (4, 4, "Mumbai WH", 120, "2024-06-20"),
            (5, 5, "Chennai WH", 45, "2024-06-20"),
            (6, 6, "Delhi WH", 90, "2024-06-20"),
            (7, 7, "Mumbai WH", 60, "2024-06-20"),
        ]
        conn.executemany(
            "INSERT INTO inventory (inventory_id, product_id, warehouse, stock_level, updated_at) VALUES (?,?,?,?,?)",
            inventory,
        )
        conn.commit()
    finally:
        conn.close()


def ensure_seeded(db_path: Path) -> None:
    if not db_path.exists() or db_path.stat().st_size == 0:
        seed_database(db_path)