-- =====================================================================
-- 02_staging_load.sql  --  bulk-load the 9 raw CSVs into a staging schema
-- All columns are TEXT so nothing is rejected at this step; cleaning
-- and type casting happen in 03_transform.sql.
-- Needs two psql variables (setup_db.bat passes them for you):
--   datadir = folder holding the CSVs,  dbdir = this db folder
--   psql -U postgres -d olist -v datadir="C:/Users/you/Downloads/Dataset" -v dbdir="C:/.../olist-dbms/db" -f 00_run_all.sql
-- =====================================================================
SET client_encoding = 'UTF8';
SET client_min_messages = warning;

DROP SCHEMA IF EXISTS staging CASCADE;
CREATE SCHEMA staging;

CREATE TABLE staging.customers (customer_id TEXT, customer_unique_id TEXT,
    customer_zip_code_prefix TEXT, customer_city TEXT, customer_state TEXT);
CREATE TABLE staging.geolocation (zip_prefix TEXT, lat TEXT, lng TEXT, city TEXT, state TEXT);
CREATE TABLE staging.order_items (order_id TEXT, order_item_id TEXT, product_id TEXT,
    seller_id TEXT, shipping_limit_date TEXT, price TEXT, freight_value TEXT);
CREATE TABLE staging.payments (order_id TEXT, payment_sequential TEXT, payment_type TEXT,
    payment_installments TEXT, payment_value TEXT);
CREATE TABLE staging.reviews (review_id TEXT, order_id TEXT, review_score TEXT,
    review_comment_title TEXT, review_comment_message TEXT,
    review_creation_date TEXT, review_answer_timestamp TEXT);
CREATE TABLE staging.orders (order_id TEXT, customer_id TEXT, order_status TEXT,
    order_purchase_timestamp TEXT, order_approved_at TEXT, order_delivered_carrier_date TEXT,
    order_delivered_customer_date TEXT, order_estimated_delivery_date TEXT);
CREATE TABLE staging.products (product_id TEXT, product_category_name TEXT,
    product_name_lenght TEXT, product_description_lenght TEXT, product_photos_qty TEXT,
    product_weight_g TEXT, product_length_cm TEXT, product_height_cm TEXT, product_width_cm TEXT);
CREATE TABLE staging.sellers (seller_id TEXT, seller_zip_code_prefix TEXT,
    seller_city TEXT, seller_state TEXT);
CREATE TABLE staging.category_translation (product_category_name TEXT,
    product_category_name_english TEXT);

\echo Loading CSV files from :datadir ...
\cd :datadir
\copy staging.customers FROM 'olist_customers_dataset.csv' WITH (FORMAT csv, HEADER true)
\copy staging.geolocation FROM 'olist_geolocation_dataset.csv' WITH (FORMAT csv, HEADER true)
\copy staging.order_items FROM 'olist_order_items_dataset.csv' WITH (FORMAT csv, HEADER true)
\copy staging.payments FROM 'olist_order_payments_dataset.csv' WITH (FORMAT csv, HEADER true)
\copy staging.reviews FROM 'olist_order_reviews_dataset.csv' WITH (FORMAT csv, HEADER true)
\copy staging.orders FROM 'olist_orders_dataset.csv' WITH (FORMAT csv, HEADER true)
\copy staging.products FROM 'olist_products_dataset.csv' WITH (FORMAT csv, HEADER true)
\copy staging.sellers FROM 'olist_sellers_dataset.csv' WITH (FORMAT csv, HEADER true)
\copy staging.category_translation FROM 'product_category_name_translation.csv' WITH (FORMAT csv, HEADER true)
\cd :dbdir

SELECT 'customers' AS staging_table, COUNT(*) FROM staging.customers
UNION ALL SELECT 'geolocation', COUNT(*) FROM staging.geolocation
UNION ALL SELECT 'order_items', COUNT(*) FROM staging.order_items
UNION ALL SELECT 'payments',    COUNT(*) FROM staging.payments
UNION ALL SELECT 'reviews',     COUNT(*) FROM staging.reviews
UNION ALL SELECT 'orders',      COUNT(*) FROM staging.orders
UNION ALL SELECT 'products',    COUNT(*) FROM staging.products
UNION ALL SELECT 'sellers',     COUNT(*) FROM staging.sellers
UNION ALL SELECT 'category_translation', COUNT(*) FROM staging.category_translation;
