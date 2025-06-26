-- schema.sql

-- Drop tables if they exist to start with a clean slate.
-- This is useful for re-running the script for testing.
DROP TABLE IF EXISTS sales;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS customers;

-- Create the customers table
CREATE TABLE customers (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(255) NOT NULL,
    signup_date DATE NOT NULL
);

-- Create the products table
CREATE TABLE products (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(100),
    price DECIMAL(10, 2) NOT NULL
);

-- Create the sales table
CREATE TABLE sales (
    id INT PRIMARY KEY AUTO_INCREMENT,
    customer_id INT,
    product_id INT,
    sale_date DATE NOT NULL,
    quantity INT NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

-- Insert sample data into customers
INSERT INTO customers (name, signup_date) VALUES
('Alice Johnson', '2023-01-15'),
('Bob Smith', '2023-02-20'),
('Charlie Brown', '2023-03-05');

-- Insert sample data into products
INSERT INTO products (name, category, price) VALUES
('Laptop', 'Electronics', 1200.00),
('Mouse', 'Electronics', 25.50),
('Desk Chair', 'Furniture', 150.75),
('Keyboard', 'Electronics', 75.00);

-- Insert sample data into sales
-- Note: customer_id and product_id correspond to the IDs from the tables above.
-- Alice (id=1) buys a Laptop (id=1)
INSERT INTO sales (customer_id, product_id, sale_date, quantity) VALUES
(1, 1, '2023-04-01', 1);

-- Bob (id=2) buys a Mouse (id=2) and a Keyboard (id=4)
INSERT INTO sales (customer_id, product_id, sale_date, quantity) VALUES
(2, 2, '2023-04-02', 2),
(2, 4, '2023-04-02', 1);

-- Alice (id=1) buys a Desk Chair (id=3)
INSERT INTO sales (customer_id, product_id, sale_date, quantity) VALUES
(1, 3, '2023-04-05', 1);

-- Charlie (id=3) buys a Laptop (id=1)
INSERT INTO sales (customer_id, product_id, sale_date, quantity) VALUES
(3, 1, '2023-04-10', 1);