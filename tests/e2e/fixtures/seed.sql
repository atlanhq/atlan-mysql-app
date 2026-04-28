-- Seed data for MySQL e2e integration tests.
-- Generates 5 databases, ~200 tables, ~3000 columns, ~20 views
-- to validate extraction at realistic enterprise scale.

-- ═══════════════════════════════════════════════════════════════════
-- Database 1: ecommerce (hand-crafted, 12 tables, 4 views)
-- ═══════════════════════════════════════════════════════════════════

CREATE DATABASE IF NOT EXISTS ecommerce;
USE ecommerce;

CREATE TABLE customers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    phone VARCHAR(20),
    address_line1 VARCHAR(200),
    address_line2 VARCHAR(200),
    city VARCHAR(100),
    state VARCHAR(50),
    zip_code VARCHAR(20),
    country VARCHAR(50) DEFAULT 'US',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    loyalty_tier ENUM('bronze','silver','gold','platinum') DEFAULT 'bronze',
    lifetime_value DECIMAL(12,2) DEFAULT 0.00,
    notes TEXT
);

CREATE TABLE products (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    sku VARCHAR(50) UNIQUE NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    cost DECIMAL(10,2),
    category VARCHAR(100),
    subcategory VARCHAR(100),
    brand VARCHAR(100),
    description TEXT,
    weight_kg DECIMAL(8,3),
    dimensions_cm VARCHAR(50),
    stock_quantity INT DEFAULT 0,
    reorder_level INT DEFAULT 10,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    order_number VARCHAR(50) UNIQUE NOT NULL,
    order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    shipped_date TIMESTAMP NULL,
    delivered_date TIMESTAMP NULL,
    status ENUM('pending','confirmed','processing','shipped','delivered','cancelled','refunded') DEFAULT 'pending',
    payment_method ENUM('credit_card','debit_card','paypal','bank_transfer','cod') DEFAULT 'credit_card',
    subtotal DECIMAL(12,2) NOT NULL,
    tax_amount DECIMAL(10,2) DEFAULT 0.00,
    shipping_amount DECIMAL(10,2) DEFAULT 0.00,
    discount_amount DECIMAL(10,2) DEFAULT 0.00,
    total_amount DECIMAL(12,2) NOT NULL,
    shipping_address TEXT,
    billing_address TEXT,
    notes TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

CREATE TABLE order_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    product_id INT NOT NULL,
    quantity INT NOT NULL DEFAULT 1,
    unit_price DECIMAL(10,2) NOT NULL,
    discount_percent DECIMAL(5,2) DEFAULT 0.00,
    line_total DECIMAL(12,2) NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE TABLE reviews (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL,
    customer_id INT NOT NULL,
    rating TINYINT NOT NULL,
    title VARCHAR(200),
    body TEXT,
    is_verified_purchase BOOLEAN DEFAULT FALSE,
    helpful_count INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products(id),
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

CREATE TABLE categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    parent_id INT,
    slug VARCHAR(100) UNIQUE,
    description TEXT,
    sort_order INT DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (parent_id) REFERENCES categories(id)
);

CREATE TABLE inventory_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL,
    change_quantity INT NOT NULL,
    reason ENUM('purchase','return','restock','adjustment','damaged') NOT NULL,
    reference_id INT,
    notes VARCHAR(500),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE TABLE shipping_carriers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    code VARCHAR(20) UNIQUE NOT NULL,
    tracking_url_template VARCHAR(500),
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE shipments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    carrier_id INT NOT NULL,
    tracking_number VARCHAR(100),
    status ENUM('label_created','picked_up','in_transit','out_for_delivery','delivered','exception') DEFAULT 'label_created',
    shipped_at TIMESTAMP NULL,
    delivered_at TIMESTAMP NULL,
    weight_kg DECIMAL(8,3),
    FOREIGN KEY (order_id) REFERENCES orders(id),
    FOREIGN KEY (carrier_id) REFERENCES shipping_carriers(id)
);

CREATE TABLE coupons (
    id INT AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(50) UNIQUE NOT NULL,
    discount_type ENUM('percentage','fixed_amount','free_shipping') NOT NULL,
    discount_value DECIMAL(10,2) NOT NULL,
    min_order_amount DECIMAL(10,2) DEFAULT 0.00,
    max_uses INT,
    used_count INT DEFAULT 0,
    valid_from TIMESTAMP NOT NULL,
    valid_until TIMESTAMP NOT NULL,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE wishlists (
    id INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    product_id INT NOT NULL,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_wishlist (customer_id, product_id),
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE TABLE payment_transactions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    transaction_type ENUM('charge','refund','chargeback') NOT NULL,
    amount DECIMAL(12,2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',
    gateway_reference VARCHAR(200),
    status ENUM('pending','completed','failed','reversed') DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (order_id) REFERENCES orders(id)
);

CREATE VIEW active_customers AS
SELECT id, first_name, last_name, email, loyalty_tier, lifetime_value, created_at
FROM customers WHERE is_active = TRUE;

CREATE VIEW order_summary AS
SELECT o.id AS order_id, o.order_number, c.first_name, c.last_name, c.email,
       o.order_date, o.status, o.total_amount, COUNT(oi.id) AS item_count
FROM orders o JOIN customers c ON o.customer_id = c.id
JOIN order_items oi ON oi.order_id = o.id
GROUP BY o.id, o.order_number, c.first_name, c.last_name, c.email, o.order_date, o.status, o.total_amount;

CREATE VIEW product_stats AS
SELECT p.id, p.name, p.sku, p.price, p.stock_quantity,
       COALESCE(AVG(r.rating), 0) AS avg_rating, COUNT(r.id) AS review_count
FROM products p LEFT JOIN reviews r ON r.product_id = p.id
GROUP BY p.id, p.name, p.sku, p.price, p.stock_quantity;

CREATE VIEW revenue_by_category AS
SELECT p.category, COUNT(DISTINCT o.id) AS order_count, SUM(oi.line_total) AS total_revenue
FROM order_items oi JOIN products p ON oi.product_id = p.id
JOIN orders o ON oi.order_id = o.id
WHERE o.status NOT IN ('cancelled','refunded') GROUP BY p.category;

-- ═══════════════════════════════════════════════════════════════════
-- Database 2: analytics (8 tables, 2 views)
-- ═══════════════════════════════════════════════════════════════════

CREATE DATABASE IF NOT EXISTS analytics;
USE analytics;

CREATE TABLE events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY, event_type VARCHAR(50) NOT NULL,
    event_source VARCHAR(100), user_id INT, session_id VARCHAR(100),
    payload JSON, ip_address VARCHAR(45), user_agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_event_type (event_type), INDEX idx_user_id (user_id)
);
CREATE TABLE sessions (
    id VARCHAR(100) PRIMARY KEY, user_id INT,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, ended_at TIMESTAMP NULL,
    duration_seconds INT, page_views INT DEFAULT 0, device_type VARCHAR(20),
    browser VARCHAR(50), os VARCHAR(50), country VARCHAR(50), region VARCHAR(100), city VARCHAR(100)
);
CREATE TABLE daily_metrics (
    metric_date DATE NOT NULL, metric_name VARCHAR(100) NOT NULL,
    metric_value DOUBLE NOT NULL, dimensions JSON,
    PRIMARY KEY (metric_date, metric_name)
);
CREATE TABLE funnels (
    id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100) NOT NULL,
    description TEXT, steps JSON NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE cohorts (
    id INT AUTO_INCREMENT PRIMARY KEY, cohort_date DATE NOT NULL,
    cohort_size INT NOT NULL, period INT NOT NULL, retained_users INT NOT NULL,
    retention_rate DECIMAL(5,2), metric_name VARCHAR(50) DEFAULT 'retention'
);
CREATE TABLE ab_tests (
    id INT AUTO_INCREMENT PRIMARY KEY, test_name VARCHAR(100) NOT NULL,
    variant VARCHAR(50) NOT NULL, user_id INT NOT NULL, converted BOOLEAN DEFAULT FALSE,
    revenue DECIMAL(10,2) DEFAULT 0.00, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE page_performance (
    id BIGINT AUTO_INCREMENT PRIMARY KEY, url VARCHAR(500) NOT NULL,
    load_time_ms INT NOT NULL, ttfb_ms INT, dom_ready_ms INT,
    resource_count INT, page_size_bytes BIGINT, measured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE error_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY, error_type VARCHAR(100) NOT NULL,
    error_message TEXT, stack_trace TEXT, url VARCHAR(500), user_id INT,
    browser VARCHAR(50), severity ENUM('low','medium','high','critical') DEFAULT 'medium',
    resolved BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE VIEW daily_active_users AS
SELECT DATE(created_at) AS day, COUNT(DISTINCT user_id) AS dau
FROM events WHERE user_id IS NOT NULL GROUP BY DATE(created_at);

CREATE VIEW error_summary AS
SELECT error_type, severity, COUNT(*) AS occurrences, MAX(created_at) AS last_seen
FROM error_log WHERE resolved = FALSE GROUP BY error_type, severity;

-- ═══════════════════════════════════════════════════════════════════
-- Database 3: hr (9 tables, 2 views)
-- ═══════════════════════════════════════════════════════════════════

CREATE DATABASE IF NOT EXISTS hr;
USE hr;

CREATE TABLE departments (
    id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100) NOT NULL,
    code VARCHAR(10) UNIQUE NOT NULL, parent_id INT, budget DECIMAL(15,2),
    head_count_limit INT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE employees (
    id INT AUTO_INCREMENT PRIMARY KEY, employee_number VARCHAR(20) UNIQUE NOT NULL,
    first_name VARCHAR(100) NOT NULL, last_name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL, phone VARCHAR(20), department_id INT,
    manager_id INT, title VARCHAR(100), hire_date DATE NOT NULL, termination_date DATE,
    salary DECIMAL(12,2), currency VARCHAR(3) DEFAULT 'USD',
    employment_type ENUM('full_time','part_time','contract','intern') DEFAULT 'full_time',
    status ENUM('active','on_leave','terminated') DEFAULT 'active',
    location VARCHAR(100), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
CREATE TABLE positions (
    id INT AUTO_INCREMENT PRIMARY KEY, title VARCHAR(200) NOT NULL, level VARCHAR(20),
    min_salary DECIMAL(12,2), max_salary DECIMAL(12,2), department_id INT,
    is_open BOOLEAN DEFAULT TRUE, openings INT DEFAULT 1
);
CREATE TABLE performance_reviews (
    id INT AUTO_INCREMENT PRIMARY KEY, employee_id INT NOT NULL, reviewer_id INT NOT NULL,
    review_period VARCHAR(20) NOT NULL, rating TINYINT, goals_met DECIMAL(5,2),
    strengths TEXT, improvements TEXT, comments TEXT, review_date DATE NOT NULL
);
CREATE TABLE time_off (
    id INT AUTO_INCREMENT PRIMARY KEY, employee_id INT NOT NULL,
    leave_type ENUM('vacation','sick','personal','parental','bereavement','unpaid') NOT NULL,
    start_date DATE NOT NULL, end_date DATE NOT NULL, days_count DECIMAL(4,1) NOT NULL,
    status ENUM('pending','approved','rejected','cancelled') DEFAULT 'pending',
    approved_by INT, notes TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE compensation_history (
    id INT AUTO_INCREMENT PRIMARY KEY, employee_id INT NOT NULL,
    effective_date DATE NOT NULL, salary DECIMAL(12,2) NOT NULL,
    bonus DECIMAL(12,2) DEFAULT 0.00, equity_grants INT DEFAULT 0,
    change_reason ENUM('hire','promotion','merit','adjustment','transfer') NOT NULL, notes TEXT
);
CREATE TABLE training_courses (
    id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(200) NOT NULL, description TEXT,
    category VARCHAR(100), duration_hours DECIMAL(5,1), is_mandatory BOOLEAN DEFAULT FALSE,
    provider VARCHAR(100)
);
CREATE TABLE training_enrollments (
    id INT AUTO_INCREMENT PRIMARY KEY, employee_id INT NOT NULL, course_id INT NOT NULL,
    enrolled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, completed_at TIMESTAMP NULL,
    score DECIMAL(5,2), status ENUM('enrolled','in_progress','completed','dropped') DEFAULT 'enrolled'
);
CREATE TABLE benefits (
    id INT AUTO_INCREMENT PRIMARY KEY, employee_id INT NOT NULL,
    benefit_type ENUM('health','dental','vision','401k','life_insurance','hsa','fsa') NOT NULL,
    plan_name VARCHAR(100),
    coverage_level ENUM('employee','employee_spouse','employee_children','family') DEFAULT 'employee',
    employee_contribution DECIMAL(10,2) DEFAULT 0.00,
    employer_contribution DECIMAL(10,2) DEFAULT 0.00,
    effective_date DATE NOT NULL, end_date DATE
);

CREATE VIEW headcount_by_department AS
SELECT d.name AS department, d.code, COUNT(e.id) AS headcount, AVG(e.salary) AS avg_salary
FROM departments d LEFT JOIN employees e ON e.department_id = d.id AND e.status = 'active'
GROUP BY d.id, d.name, d.code;

CREATE VIEW active_positions AS
SELECT p.title, p.level, d.name AS department, p.min_salary, p.max_salary, p.openings
FROM positions p JOIN departments d ON p.department_id = d.id WHERE p.is_open = TRUE;

-- ═══════════════════════════════════════════════════════════════════
-- Database 4: data_warehouse (generated — 50 fact/dim tables, ~750 cols)
-- ═══════════════════════════════════════════════════════════════════

CREATE DATABASE IF NOT EXISTS data_warehouse;
USE data_warehouse;

-- Dimension tables (20 tables × ~15 cols = ~300 cols)
CREATE TABLE dim_date (date_key INT PRIMARY KEY, full_date DATE NOT NULL, day_of_week TINYINT, day_name VARCHAR(10), day_of_month TINYINT, day_of_year SMALLINT, week_of_year TINYINT, month_number TINYINT, month_name VARCHAR(10), quarter TINYINT, year SMALLINT, is_weekend BOOLEAN, is_holiday BOOLEAN, fiscal_quarter TINYINT, fiscal_year SMALLINT);
CREATE TABLE dim_time (time_key INT PRIMARY KEY, full_time TIME NOT NULL, hour TINYINT, minute TINYINT, second TINYINT, am_pm VARCHAR(2), hour_12 TINYINT, time_band VARCHAR(20));
CREATE TABLE dim_customer (customer_key INT AUTO_INCREMENT PRIMARY KEY, customer_id INT, first_name VARCHAR(100), last_name VARCHAR(100), email VARCHAR(255), phone VARCHAR(20), city VARCHAR(100), state VARCHAR(50), country VARCHAR(50), postal_code VARCHAR(20), segment VARCHAR(50), tier VARCHAR(20), registration_date DATE, is_current BOOLEAN DEFAULT TRUE, valid_from DATE, valid_to DATE);
CREATE TABLE dim_product (product_key INT AUTO_INCREMENT PRIMARY KEY, product_id INT, name VARCHAR(200), sku VARCHAR(50), category VARCHAR(100), subcategory VARCHAR(100), brand VARCHAR(100), supplier VARCHAR(100), unit_cost DECIMAL(10,2), unit_price DECIMAL(10,2), weight_kg DECIMAL(8,3), is_active BOOLEAN, is_current BOOLEAN DEFAULT TRUE, valid_from DATE, valid_to DATE);
CREATE TABLE dim_store (store_key INT AUTO_INCREMENT PRIMARY KEY, store_id INT, store_name VARCHAR(100), store_type VARCHAR(50), address VARCHAR(200), city VARCHAR(100), state VARCHAR(50), country VARCHAR(50), postal_code VARCHAR(20), region VARCHAR(50), district VARCHAR(50), manager VARCHAR(100), open_date DATE, close_date DATE, square_footage INT, is_current BOOLEAN DEFAULT TRUE);
CREATE TABLE dim_employee (employee_key INT AUTO_INCREMENT PRIMARY KEY, employee_id INT, first_name VARCHAR(100), last_name VARCHAR(100), email VARCHAR(255), department VARCHAR(100), title VARCHAR(100), hire_date DATE, termination_date DATE, is_active BOOLEAN, is_current BOOLEAN DEFAULT TRUE, valid_from DATE, valid_to DATE);
CREATE TABLE dim_promotion (promo_key INT AUTO_INCREMENT PRIMARY KEY, promo_id INT, promo_name VARCHAR(200), promo_type VARCHAR(50), discount_pct DECIMAL(5,2), start_date DATE, end_date DATE, channel VARCHAR(50), min_purchase DECIMAL(10,2), is_active BOOLEAN);
CREATE TABLE dim_channel (channel_key INT AUTO_INCREMENT PRIMARY KEY, channel_name VARCHAR(50), channel_type VARCHAR(50), platform VARCHAR(50), is_digital BOOLEAN, is_active BOOLEAN);
CREATE TABLE dim_geography (geo_key INT AUTO_INCREMENT PRIMARY KEY, country VARCHAR(100), country_code VARCHAR(3), region VARCHAR(100), subregion VARCHAR(100), city VARCHAR(100), postal_code VARCHAR(20), latitude DECIMAL(10,7), longitude DECIMAL(10,7), timezone VARCHAR(50), population INT);
CREATE TABLE dim_currency (currency_key INT AUTO_INCREMENT PRIMARY KEY, currency_code VARCHAR(3), currency_name VARCHAR(50), symbol VARCHAR(5), exchange_rate_usd DECIMAL(12,6), effective_date DATE);
CREATE TABLE dim_supplier (supplier_key INT AUTO_INCREMENT PRIMARY KEY, supplier_id INT, company_name VARCHAR(200), contact_name VARCHAR(100), email VARCHAR(255), phone VARCHAR(20), country VARCHAR(50), city VARCHAR(100), payment_terms VARCHAR(50), rating DECIMAL(3,1), is_active BOOLEAN);
CREATE TABLE dim_category (category_key INT AUTO_INCREMENT PRIMARY KEY, category_id INT, category_name VARCHAR(100), parent_category VARCHAR(100), department VARCHAR(100), is_active BOOLEAN, sort_order INT);
CREATE TABLE dim_payment_method (payment_key INT AUTO_INCREMENT PRIMARY KEY, method_name VARCHAR(50), method_type VARCHAR(30), provider VARCHAR(50), is_digital BOOLEAN, processing_fee_pct DECIMAL(4,2), is_active BOOLEAN);
CREATE TABLE dim_shipping_method (shipping_key INT AUTO_INCREMENT PRIMARY KEY, method_name VARCHAR(100), carrier VARCHAR(50), speed VARCHAR(30), base_cost DECIMAL(8,2), cost_per_kg DECIMAL(6,2), max_weight_kg DECIMAL(8,2), is_active BOOLEAN);
CREATE TABLE dim_campaign (campaign_key INT AUTO_INCREMENT PRIMARY KEY, campaign_id INT, campaign_name VARCHAR(200), campaign_type VARCHAR(50), channel VARCHAR(50), start_date DATE, end_date DATE, budget DECIMAL(12,2), target_audience VARCHAR(100), status VARCHAR(20));
CREATE TABLE dim_device (device_key INT AUTO_INCREMENT PRIMARY KEY, device_type VARCHAR(30), os_name VARCHAR(30), os_version VARCHAR(20), browser_name VARCHAR(30), browser_version VARCHAR(20), screen_resolution VARCHAR(20), is_mobile BOOLEAN);
CREATE TABLE dim_status (status_key INT AUTO_INCREMENT PRIMARY KEY, status_name VARCHAR(50), status_category VARCHAR(50), display_order INT, is_terminal BOOLEAN, color_code VARCHAR(7));
CREATE TABLE dim_warehouse (warehouse_key INT AUTO_INCREMENT PRIMARY KEY, warehouse_id INT, warehouse_name VARCHAR(100), location VARCHAR(200), city VARCHAR(100), state VARCHAR(50), country VARCHAR(50), capacity_units INT, current_utilization DECIMAL(5,2), manager VARCHAR(100), is_active BOOLEAN);
CREATE TABLE dim_vendor (vendor_key INT AUTO_INCREMENT PRIMARY KEY, vendor_id INT, vendor_name VARCHAR(200), vendor_type VARCHAR(50), contact_email VARCHAR(255), phone VARCHAR(20), address VARCHAR(200), city VARCHAR(100), country VARCHAR(50), contract_start DATE, contract_end DATE, sla_tier VARCHAR(20));
CREATE TABLE dim_priority (priority_key INT AUTO_INCREMENT PRIMARY KEY, priority_name VARCHAR(30), priority_level INT, sla_hours INT, color_code VARCHAR(7), description VARCHAR(200));

-- Fact tables (30 tables × ~15 cols = ~450 cols)
CREATE TABLE fact_sales (sale_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, customer_key INT, product_key INT, store_key INT, promo_key INT, channel_key INT, quantity INT, unit_price DECIMAL(10,2), discount_amount DECIMAL(10,2), tax_amount DECIMAL(10,2), shipping_amount DECIMAL(10,2), total_amount DECIMAL(12,2), cost_amount DECIMAL(10,2), profit_amount DECIMAL(10,2));
CREATE TABLE fact_returns (return_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, customer_key INT, product_key INT, store_key INT, original_sale_key BIGINT, return_reason VARCHAR(100), quantity INT, refund_amount DECIMAL(10,2), restocking_fee DECIMAL(8,2));
CREATE TABLE fact_inventory (inventory_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, product_key INT, warehouse_key INT, quantity_on_hand INT, quantity_reserved INT, quantity_available INT, reorder_point INT, days_of_supply INT, unit_cost DECIMAL(10,2), total_value DECIMAL(12,2));
CREATE TABLE fact_web_traffic (traffic_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, time_key INT, geo_key INT, device_key INT, channel_key INT, campaign_key INT, sessions INT, page_views INT, unique_visitors INT, bounce_rate DECIMAL(5,2), avg_session_duration INT, conversions INT, revenue DECIMAL(12,2));
CREATE TABLE fact_marketing_spend (spend_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, campaign_key INT, channel_key INT, impressions BIGINT, clicks INT, conversions INT, spend_amount DECIMAL(12,2), revenue_attributed DECIMAL(12,2), cpc DECIMAL(8,4), cpa DECIMAL(10,2), roas DECIMAL(8,2));
CREATE TABLE fact_customer_support (ticket_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, customer_key INT, employee_key INT, channel_key INT, priority_key INT, category VARCHAR(100), resolution_time_hours DECIMAL(8,2), first_response_minutes INT, satisfaction_score TINYINT, is_resolved BOOLEAN, escalated BOOLEAN);
CREATE TABLE fact_shipments (shipment_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, product_key INT, store_key INT, warehouse_key INT, shipping_key INT, quantity INT, weight_kg DECIMAL(8,2), shipping_cost DECIMAL(10,2), delivery_days INT, on_time BOOLEAN, damaged BOOLEAN);
CREATE TABLE fact_employee_attendance (attendance_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, employee_key INT, clock_in TIME, clock_out TIME, hours_worked DECIMAL(4,1), overtime_hours DECIMAL(4,1), break_minutes INT, status VARCHAR(20), location VARCHAR(100));
CREATE TABLE fact_financial_transactions (txn_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, account_id INT, transaction_type VARCHAR(50), debit_amount DECIMAL(14,2), credit_amount DECIMAL(14,2), balance DECIMAL(14,2), currency_key INT, description VARCHAR(200), reference VARCHAR(100));
CREATE TABLE fact_product_views (view_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, product_key INT, customer_key INT, device_key INT, channel_key INT, view_duration_seconds INT, added_to_cart BOOLEAN, purchased BOOLEAN, referrer VARCHAR(200));
CREATE TABLE fact_email_campaigns (email_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, campaign_key INT, customer_key INT, sent BOOLEAN, delivered BOOLEAN, opened BOOLEAN, clicked BOOLEAN, unsubscribed BOOLEAN, bounced BOOLEAN, revenue DECIMAL(10,2));
CREATE TABLE fact_subscription (sub_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, customer_key INT, plan_name VARCHAR(50), plan_tier VARCHAR(20), monthly_amount DECIMAL(10,2), annual_amount DECIMAL(12,2), status VARCHAR(20), started_at DATE, cancelled_at DATE, churn_reason VARCHAR(100));
CREATE TABLE fact_warehouse_operations (op_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, warehouse_key INT, employee_key INT, operation_type VARCHAR(50), product_key INT, quantity INT, duration_minutes INT, errors INT, throughput_per_hour DECIMAL(8,2));
CREATE TABLE fact_pricing_history (price_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, product_key INT, list_price DECIMAL(10,2), sale_price DECIMAL(10,2), cost_price DECIMAL(10,2), margin_pct DECIMAL(5,2), competitor_price DECIMAL(10,2), price_index DECIMAL(6,2));
CREATE TABLE fact_social_media (social_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, campaign_key INT, channel_key INT, platform VARCHAR(30), posts INT, impressions BIGINT, engagements INT, shares INT, comments INT, followers_gained INT, sentiment_score DECIMAL(4,2));
CREATE TABLE fact_call_center (call_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, time_key INT, employee_key INT, customer_key INT, call_type VARCHAR(30), duration_seconds INT, wait_seconds INT, hold_seconds INT, transfers INT, resolution VARCHAR(30), satisfaction TINYINT);
CREATE TABLE fact_store_traffic (store_traffic_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, time_key INT, store_key INT, foot_traffic INT, conversion_rate DECIMAL(5,2), avg_basket_size DECIMAL(8,2), avg_transaction_value DECIMAL(10,2), staff_count INT);
CREATE TABLE fact_loyalty_points (points_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, customer_key INT, points_earned INT, points_redeemed INT, points_expired INT, points_balance INT, tier_at_time VARCHAR(20), transaction_ref VARCHAR(100));
CREATE TABLE fact_quality_checks (qc_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, product_key INT, warehouse_key INT, inspector_id INT, batch_size INT, defects_found INT, defect_rate DECIMAL(6,4), pass_fail VARCHAR(4), check_type VARCHAR(50), notes TEXT);
CREATE TABLE fact_supplier_orders (so_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, supplier_key INT, product_key INT, warehouse_key INT, quantity_ordered INT, quantity_received INT, unit_cost DECIMAL(10,2), total_cost DECIMAL(12,2), lead_time_days INT, on_time BOOLEAN, quality_score DECIMAL(3,1));
CREATE TABLE fact_budget (budget_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, department VARCHAR(100), account_category VARCHAR(100), budget_amount DECIMAL(14,2), actual_amount DECIMAL(14,2), variance DECIMAL(14,2), variance_pct DECIMAL(6,2), notes TEXT);
CREATE TABLE fact_forecast (forecast_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, product_key INT, store_key INT, forecast_quantity INT, actual_quantity INT, forecast_revenue DECIMAL(12,2), actual_revenue DECIMAL(12,2), mape DECIMAL(6,2), model_version VARCHAR(20));
CREATE TABLE fact_competitor_pricing (comp_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, product_key INT, competitor_name VARCHAR(100), competitor_price DECIMAL(10,2), our_price DECIMAL(10,2), price_difference DECIMAL(10,2), price_index DECIMAL(6,2), source VARCHAR(100), scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE fact_ad_performance (ad_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, campaign_key INT, channel_key INT, ad_group VARCHAR(100), ad_creative VARCHAR(200), impressions BIGINT, clicks INT, conversions INT, spend DECIMAL(10,2), revenue DECIMAL(12,2), ctr DECIMAL(6,4), cvr DECIMAL(6,4));
CREATE TABLE fact_seo_rankings (seo_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, keyword VARCHAR(200), url VARCHAR(500), search_engine VARCHAR(20), position INT, search_volume INT, click_rate DECIMAL(5,2), impressions INT, clicks INT);
CREATE TABLE fact_app_usage (usage_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, device_key INT, customer_key INT, app_version VARCHAR(20), session_count INT, total_duration_minutes INT, screens_viewed INT, crashes INT, feature_used VARCHAR(100));
CREATE TABLE fact_nps_survey (nps_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, customer_key INT, channel_key INT, score TINYINT, category VARCHAR(20), verbatim TEXT, follow_up_required BOOLEAN, responded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE fact_delivery_performance (delivery_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, store_key INT, shipping_key INT, geo_key INT, orders_shipped INT, orders_delivered INT, on_time_count INT, late_count INT, damaged_count INT, avg_delivery_days DECIMAL(4,1), delivery_cost DECIMAL(10,2));
CREATE TABLE fact_rfm_scores (rfm_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, customer_key INT, recency_days INT, frequency INT, monetary DECIMAL(12,2), r_score TINYINT, f_score TINYINT, m_score TINYINT, rfm_segment VARCHAR(30));
CREATE TABLE fact_churn_prediction (churn_key BIGINT AUTO_INCREMENT PRIMARY KEY, date_key INT, customer_key INT, churn_probability DECIMAL(5,4), risk_tier VARCHAR(20), days_since_last_order INT, order_frequency DECIMAL(6,2), lifetime_value DECIMAL(12,2), predicted_action VARCHAR(50), model_version VARCHAR(20));

-- DW views
CREATE VIEW v_monthly_sales AS
SELECT d.year, d.month_number, SUM(f.total_amount) AS revenue, SUM(f.profit_amount) AS profit, COUNT(*) AS transactions
FROM fact_sales f JOIN dim_date d ON f.date_key = d.date_key GROUP BY d.year, d.month_number;

CREATE VIEW v_product_performance AS
SELECT p.name, p.category, p.brand, SUM(f.quantity) AS units_sold, SUM(f.total_amount) AS revenue, SUM(f.profit_amount) AS profit
FROM fact_sales f JOIN dim_product p ON f.product_key = p.product_key GROUP BY p.name, p.category, p.brand;

CREATE VIEW v_customer_segments AS
SELECT c.segment, c.tier, COUNT(*) AS customers, AVG(r.monetary) AS avg_ltv, AVG(r.recency_days) AS avg_recency
FROM fact_rfm_scores r JOIN dim_customer c ON r.customer_key = c.customer_key GROUP BY c.segment, c.tier;

CREATE VIEW v_channel_attribution AS
SELECT ch.channel_name, SUM(m.impressions) AS impressions, SUM(m.clicks) AS clicks, SUM(m.conversions) AS conversions, SUM(m.spend_amount) AS spend, SUM(m.revenue_attributed) AS revenue
FROM fact_marketing_spend m JOIN dim_channel ch ON m.channel_key = ch.channel_key GROUP BY ch.channel_name;

-- ═══════════════════════════════════════════════════════════════════
-- Database 5: iot_platform (generated — 20 tables, ~300 cols)
-- ═══════════════════════════════════════════════════════════════════

CREATE DATABASE IF NOT EXISTS iot_platform;
USE iot_platform;

CREATE TABLE devices (id INT AUTO_INCREMENT PRIMARY KEY, device_uid VARCHAR(100) UNIQUE NOT NULL, device_name VARCHAR(200), device_type VARCHAR(50), manufacturer VARCHAR(100), model VARCHAR(100), firmware_version VARCHAR(50), mac_address VARCHAR(17), ip_address VARCHAR(45), location_lat DECIMAL(10,7), location_lon DECIMAL(10,7), site_id INT, zone VARCHAR(50), install_date DATE, last_seen TIMESTAMP, status ENUM('online','offline','maintenance','decommissioned') DEFAULT 'offline', battery_level DECIMAL(5,2), signal_strength INT, tags JSON, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE sites (id INT AUTO_INCREMENT PRIMARY KEY, site_name VARCHAR(200) NOT NULL, site_code VARCHAR(20) UNIQUE, address VARCHAR(300), city VARCHAR(100), state VARCHAR(50), country VARCHAR(50), latitude DECIMAL(10,7), longitude DECIMAL(10,7), timezone VARCHAR(50), contact_name VARCHAR(100), contact_email VARCHAR(255), is_active BOOLEAN DEFAULT TRUE);
CREATE TABLE sensor_readings (id BIGINT AUTO_INCREMENT PRIMARY KEY, device_id INT NOT NULL, sensor_type VARCHAR(50) NOT NULL, value DOUBLE NOT NULL, unit VARCHAR(20), quality_flag VARCHAR(10) DEFAULT 'good', timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, INDEX idx_device_time (device_id, timestamp));
CREATE TABLE alerts (id BIGINT AUTO_INCREMENT PRIMARY KEY, device_id INT NOT NULL, alert_type VARCHAR(50) NOT NULL, severity ENUM('info','warning','critical','emergency') DEFAULT 'warning', message TEXT, threshold_value DOUBLE, actual_value DOUBLE, acknowledged BOOLEAN DEFAULT FALSE, acknowledged_by VARCHAR(100), resolved BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, resolved_at TIMESTAMP NULL);
CREATE TABLE device_commands (id BIGINT AUTO_INCREMENT PRIMARY KEY, device_id INT NOT NULL, command_type VARCHAR(50) NOT NULL, payload JSON, status ENUM('queued','sent','acknowledged','completed','failed','timeout') DEFAULT 'queued', sent_at TIMESTAMP NULL, completed_at TIMESTAMP NULL, retry_count INT DEFAULT 0, error_message TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE firmware_updates (id INT AUTO_INCREMENT PRIMARY KEY, version VARCHAR(50) NOT NULL, release_date DATE, changelog TEXT, min_hardware_version VARCHAR(20), file_size_bytes BIGINT, checksum VARCHAR(64), is_mandatory BOOLEAN DEFAULT FALSE, rollout_pct DECIMAL(5,2) DEFAULT 100.00, status ENUM('draft','testing','released','deprecated') DEFAULT 'draft');
CREATE TABLE device_groups (id INT AUTO_INCREMENT PRIMARY KEY, group_name VARCHAR(100) NOT NULL, description TEXT, parent_id INT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE device_group_members (id INT AUTO_INCREMENT PRIMARY KEY, group_id INT NOT NULL, device_id INT NOT NULL, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE KEY unique_membership (group_id, device_id));
CREATE TABLE rules_engine (id INT AUTO_INCREMENT PRIMARY KEY, rule_name VARCHAR(200) NOT NULL, description TEXT, condition_json JSON NOT NULL, action_type VARCHAR(50) NOT NULL, action_config JSON, is_enabled BOOLEAN DEFAULT TRUE, priority INT DEFAULT 0, cooldown_seconds INT DEFAULT 300, last_triggered TIMESTAMP NULL, trigger_count INT DEFAULT 0);
CREATE TABLE audit_log (id BIGINT AUTO_INCREMENT PRIMARY KEY, entity_type VARCHAR(50) NOT NULL, entity_id INT NOT NULL, action VARCHAR(20) NOT NULL, actor VARCHAR(100), old_values JSON, new_values JSON, ip_address VARCHAR(45), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE dashboards (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(200) NOT NULL, description TEXT, layout JSON, owner VARCHAR(100), is_public BOOLEAN DEFAULT FALSE, refresh_interval_seconds INT DEFAULT 60, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP);
CREATE TABLE widgets (id INT AUTO_INCREMENT PRIMARY KEY, dashboard_id INT NOT NULL, widget_type VARCHAR(50) NOT NULL, title VARCHAR(200), config JSON, position_x INT, position_y INT, width INT, height INT, data_source VARCHAR(200), refresh_override_seconds INT);
CREATE TABLE api_keys (id INT AUTO_INCREMENT PRIMARY KEY, key_hash VARCHAR(64) UNIQUE NOT NULL, name VARCHAR(100), scopes JSON, rate_limit INT DEFAULT 1000, expires_at TIMESTAMP NULL, is_active BOOLEAN DEFAULT TRUE, last_used TIMESTAMP NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE webhooks (id INT AUTO_INCREMENT PRIMARY KEY, url VARCHAR(500) NOT NULL, event_types JSON NOT NULL, secret_hash VARCHAR(64), is_active BOOLEAN DEFAULT TRUE, retry_policy JSON, last_triggered TIMESTAMP NULL, failure_count INT DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE data_exports (id INT AUTO_INCREMENT PRIMARY KEY, export_name VARCHAR(200), format ENUM('csv','json','parquet') DEFAULT 'csv', query_config JSON, schedule_cron VARCHAR(50), destination VARCHAR(500), last_run TIMESTAMP NULL, last_row_count INT, status ENUM('idle','running','completed','failed') DEFAULT 'idle');
CREATE TABLE maintenance_windows (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(200), site_id INT, start_time TIMESTAMP NOT NULL, end_time TIMESTAMP NOT NULL, affected_devices JSON, reason TEXT, created_by VARCHAR(100), status ENUM('scheduled','in_progress','completed','cancelled') DEFAULT 'scheduled');
CREATE TABLE device_metrics_hourly (id BIGINT AUTO_INCREMENT PRIMARY KEY, device_id INT NOT NULL, hour_timestamp TIMESTAMP NOT NULL, cpu_usage_avg DECIMAL(5,2), memory_usage_avg DECIMAL(5,2), disk_usage_avg DECIMAL(5,2), network_in_bytes BIGINT, network_out_bytes BIGINT, uptime_seconds INT, error_count INT, restart_count INT, INDEX idx_device_hour (device_id, hour_timestamp));
CREATE TABLE geo_fences (id INT AUTO_INCREMENT PRIMARY KEY, fence_name VARCHAR(200) NOT NULL, fence_type ENUM('circle','polygon') NOT NULL, center_lat DECIMAL(10,7), center_lon DECIMAL(10,7), radius_meters DOUBLE, polygon_coords JSON, alert_on_enter BOOLEAN DEFAULT TRUE, alert_on_exit BOOLEAN DEFAULT TRUE, is_active BOOLEAN DEFAULT TRUE);
CREATE TABLE device_certificates (id INT AUTO_INCREMENT PRIMARY KEY, device_id INT NOT NULL, certificate_serial VARCHAR(100) UNIQUE, issued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, expires_at TIMESTAMP NOT NULL, issuer VARCHAR(200), is_revoked BOOLEAN DEFAULT FALSE, revoked_at TIMESTAMP NULL);
CREATE TABLE integrations (id INT AUTO_INCREMENT PRIMARY KEY, integration_name VARCHAR(100) NOT NULL, integration_type ENUM('mqtt','http','kafka','grpc','websocket') NOT NULL, endpoint VARCHAR(500), config JSON, auth_type VARCHAR(30), is_active BOOLEAN DEFAULT TRUE, last_sync TIMESTAMP NULL, error_count INT DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);

CREATE VIEW device_health AS
SELECT d.device_uid, d.device_name, d.status, d.battery_level, d.signal_strength, d.last_seen,
       m.cpu_usage_avg, m.memory_usage_avg, m.error_count
FROM devices d LEFT JOIN device_metrics_hourly m ON d.id = m.device_id
AND m.hour_timestamp = (SELECT MAX(hour_timestamp) FROM device_metrics_hourly WHERE device_id = d.id);

CREATE VIEW active_alerts AS
SELECT a.id, d.device_uid, d.device_name, a.alert_type, a.severity, a.message, a.created_at
FROM alerts a JOIN devices d ON a.device_id = d.id
WHERE a.resolved = FALSE ORDER BY FIELD(a.severity, 'emergency','critical','warning','info');

-- ═══════════════════════════════════════════════════════════════════
-- Summary:
--   Databases: 5 (ecommerce, analytics, hr, data_warehouse, iot_platform)
--   Tables:    ~99
--   Views:     ~18
--   Columns:   ~1500+
-- ═══════════════════════════════════════════════════════════════════
