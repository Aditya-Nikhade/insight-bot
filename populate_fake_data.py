import os
import random
from datetime import datetime, timedelta
from faker import Faker
from sqlalchemy import create_engine, text
from decimal import Decimal
from dotenv import load_dotenv

load_dotenv()

# --- CONFIG ---
CUSTOMER_COUNT = 1000
PRODUCT_COUNT = 75
SALES_COUNT = 12000  # >10,000
CATEGORIES = [
    'Electronics', 'Furniture', 'Clothing', 'Books', 'Toys', 'Sports', 'Beauty', 'Automotive', 'Garden', 'Grocery'
]

# --- DB CONNECTION ---
db_url = os.getenv("DATABASE_URL")
engine = create_engine(db_url)

fake = Faker()

# --- DATA GENERATION ---
def clear_tables():
    with engine.connect() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0;"))
        conn.execute(text("TRUNCATE TABLE sales;"))
        conn.execute(text("TRUNCATE TABLE products;"))
        conn.execute(text("TRUNCATE TABLE customers;"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1;"))
        print("Tables cleared.")

def generate_customers():
    customers = []
    for _ in range(CUSTOMER_COUNT):
        name = fake.name()
        signup_date = fake.date_between(start_date="-2y", end_date="today")
        customers.append((name, signup_date))
    return customers

def generate_products():
    products = []
    for _ in range(PRODUCT_COUNT):
        name = fake.unique.word().capitalize() + ' ' + fake.word().capitalize()
        category = random.choice(CATEGORIES)
        price = round(random.uniform(5, 2000), 2)
        products.append((name, category, price))
    return products

def generate_sales(customer_ids, product_ids):
    sales = []
    for _ in range(SALES_COUNT):
        customer_id = random.choice(customer_ids)
        product_id = random.choice(product_ids)
        sale_date = fake.date_between(start_date="-2y", end_date="today")
        quantity = random.randint(1, 5)
        sales.append((customer_id, product_id, sale_date, quantity))
    return sales

def insert_customers(customers):
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0;"))
        conn.execute(text("TRUNCATE TABLE customers;"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1;"))
        for name, signup_date in customers:
            conn.execute(text("INSERT INTO customers (name, signup_date) VALUES (:name, :signup_date)"), {"name": name, "signup_date": signup_date})
    print(f"Inserted {len(customers)} customers.")

def insert_products(products):
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0;"))
        conn.execute(text("TRUNCATE TABLE products;"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1;"))
        for name, category, price in products:
            conn.execute(text("INSERT INTO products (name, category, price) VALUES (:name, :category, :price)"), {"name": name, "category": category, "price": price})
    print(f"Inserted {len(products)} products.")

def insert_sales(sales):
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0;"))
        conn.execute(text("TRUNCATE TABLE sales;"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1;"))
        for customer_id, product_id, sale_date, quantity in sales:
            conn.execute(text("INSERT INTO sales (customer_id, product_id, sale_date, quantity) VALUES (:customer_id, :product_id, :sale_date, :quantity)"), {
                "customer_id": customer_id,
                "product_id": product_id,
                "sale_date": sale_date,
                "quantity": quantity
            })
    print(f"Inserted {len(sales)} sales.")

def main():
    print("Clearing tables...")
    clear_tables()
    print("Generating customers...")
    customers = generate_customers()
    insert_customers(customers)
    print("Generating products...")
    products = generate_products()
    insert_products(products)
    # Get IDs for foreign key references
    with engine.connect() as conn:
        customer_ids = [row[0] for row in conn.execute(text("SELECT id FROM customers")).fetchall()]
        product_ids = [row[0] for row in conn.execute(text("SELECT id FROM products")).fetchall()]
    print("Generating sales...")
    sales = generate_sales(customer_ids, product_ids)
    insert_sales(sales)
    print("Database population complete!")

if __name__ == "__main__":
    main() 