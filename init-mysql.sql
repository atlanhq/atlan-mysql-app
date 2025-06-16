-- Initialize MySQL database with sample data for testing

-- Create a sample schema
CREATE DATABASE IF NOT EXISTS sample_schema;

USE test_db;

-- Create sample tables
CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) COMMENT='User accounts table';

CREATE TABLE orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    order_date DATE NOT NULL,
    total_amount DECIMAL(10,2) NOT NULL,
    status ENUM('pending', 'completed', 'cancelled') DEFAULT 'pending',
    FOREIGN KEY (user_id) REFERENCES users(id)
) COMMENT='Orders table';

-- Create a view
CREATE VIEW user_order_summary AS
SELECT 
    u.id,
    u.username,
    u.email,
    COUNT(o.id) as total_orders,
    COALESCE(SUM(o.total_amount), 0) as total_spent
FROM users u
LEFT JOIN orders o ON u.id = o.user_id
GROUP BY u.id, u.username, u.email;

-- Create a stored procedure
DELIMITER //
CREATE PROCEDURE GetUserOrders(IN user_id INT)
BEGIN
    SELECT * FROM orders WHERE orders.user_id = user_id;
END//
DELIMITER ;

-- Create a function
DELIMITER //
CREATE FUNCTION GetUserOrderCount(user_id INT) RETURNS INT
READS SQL DATA
DETERMINISTIC
BEGIN
    DECLARE order_count INT;
    SELECT COUNT(*) INTO order_count FROM orders WHERE orders.user_id = user_id;
    RETURN order_count;
END//
DELIMITER ;

-- Insert sample data
INSERT INTO users (username, email) VALUES
('john_doe', 'john@example.com'),
('jane_smith', 'jane@example.com'),
('bob_wilson', 'bob@example.com');

INSERT INTO orders (user_id, order_date, total_amount, status) VALUES
(1, '2024-01-15', 99.99, 'completed'),
(1, '2024-02-01', 149.50, 'completed'),
(2, '2024-01-20', 75.25, 'completed'),
(3, '2024-02-10', 299.99, 'pending');

-- Use sample_schema database for additional testing
USE sample_schema;

-- Create another table in the sample_schema
CREATE TABLE products (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    price DECIMAL(10,2) NOT NULL,
    category VARCHAR(50),
    in_stock BOOLEAN DEFAULT TRUE
) COMMENT='Products catalog';

INSERT INTO products (name, description, price, category, in_stock) VALUES
('Laptop', 'High-performance laptop', 999.99, 'Electronics', TRUE),
('Mouse', 'Wireless mouse', 29.99, 'Electronics', TRUE),
('Desk Chair', 'Ergonomic office chair', 199.99, 'Furniture', FALSE); 