-- =====================================================================
-- 03_transform.sql  --  clean staging data and INSERT ... SELECT into the
-- normalized tables. Each block fixes one data-quality issue found
-- during profiling (see the plan's "Data-quality issues" table).
-- =====================================================================
SET client_min_messages = warning;
BEGIN;

-- 1. STATE (27 Brazilian states; names and regions are reference data)
INSERT INTO state (state_code, state_name, region) VALUES
 ('AC','Acre','North'),('AL','Alagoas','Northeast'),('AM','Amazonas','North'),
 ('AP','Amapa','North'),('BA','Bahia','Northeast'),('CE','Ceara','Northeast'),
 ('DF','Distrito Federal','Central-West'),('ES','Espirito Santo','Southeast'),
 ('GO','Goias','Central-West'),('MA','Maranhao','Northeast'),('MG','Minas Gerais','Southeast'),
 ('MS','Mato Grosso do Sul','Central-West'),('MT','Mato Grosso','Central-West'),
 ('PA','Para','North'),('PB','Paraiba','Northeast'),('PE','Pernambuco','Northeast'),
 ('PI','Piaui','Northeast'),('PR','Parana','South'),('RJ','Rio de Janeiro','Southeast'),
 ('RN','Rio Grande do Norte','Northeast'),('RO','Rondonia','North'),('RR','Roraima','North'),
 ('RS','Rio Grande do Sul','South'),('SC','Santa Catarina','South'),('SE','Sergipe','Northeast'),
 ('SP','Sao Paulo','Southeast'),('TO','Tocantins','North');

-- 2. ZIP_CODE: geolocation has ~1M rows for ~19k prefixes -> one row per prefix.
--    Average lat/lng of points inside Brazil; most frequent city and state.
INSERT INTO zip_code (zip_prefix, city, state_code, lat, lng)
WITH g AS (
    SELECT zip_prefix::int AS zip_prefix, lower(city) AS city, upper(state) AS state,
           lat::numeric AS lat, lng::numeric AS lng
    FROM staging.geolocation
), coords AS (
    SELECT zip_prefix, ROUND(AVG(lat),6) AS lat, ROUND(AVG(lng),6) AS lng
    FROM g WHERE lat BETWEEN -34 AND 6 AND lng BETWEEN -74 AND -34
    GROUP BY zip_prefix
), city_rank AS (
    SELECT zip_prefix, city, state,
           ROW_NUMBER() OVER (PARTITION BY zip_prefix ORDER BY COUNT(*) DESC, city) AS rn
    FROM g GROUP BY zip_prefix, city, state
)
SELECT c.zip_prefix, c.city, c.state, co.lat, co.lng
FROM city_rank c LEFT JOIN coords co USING (zip_prefix)
WHERE c.rn = 1;

--    Prefixes used by customers/sellers but missing from geolocation (278 + 7):
--    keep them with NULL coordinates so every foreign key still holds.
INSERT INTO zip_code (zip_prefix, city, state_code)
SELECT DISTINCT ON (zip) zip, city, st
FROM (
    SELECT customer_zip_code_prefix::int AS zip, lower(customer_city) AS city, upper(customer_state) AS st
    FROM staging.customers
    UNION ALL
    SELECT seller_zip_code_prefix::int, lower(seller_city), upper(seller_state)
    FROM staging.sellers
) x
WHERE NOT EXISTS (SELECT 1 FROM zip_code z WHERE z.zip_prefix = x.zip)
ORDER BY zip, city;

-- 3. CUSTOMER (the real person) and CUSTOMER_ACCOUNT (per-order customer_id)
INSERT INTO customer (customer_unique_id)
SELECT DISTINCT customer_unique_id FROM staging.customers;

INSERT INTO customer_account (customer_id, customer_unique_id, zip_prefix)
SELECT customer_id, customer_unique_id, customer_zip_code_prefix::int
FROM staging.customers;

-- 4. SELLER
INSERT INTO seller (seller_id, zip_prefix)
SELECT seller_id, seller_zip_code_prefix::int FROM staging.sellers;

-- 5. CATEGORY (+ the 2 categories missing from the translation file)
INSERT INTO category (category_name, category_name_en)
SELECT product_category_name, product_category_name_english
FROM staging.category_translation;

INSERT INTO category (category_name, category_name_en) VALUES
 ('pc_gamer', 'pc_gamer'),
 ('portateis_cozinha_e_preparadores_de_alimentos', 'portable_kitchen_food_preparers')
ON CONFLICT DO NOTHING;

-- 6. PRODUCT (fixes the "lenght" typos; 610 uncategorised products keep NULL)
INSERT INTO product (product_id, category_name, name_length, description_length,
                     photos_qty, weight_g, length_cm, height_cm, width_cm, stock_qty)
SELECT product_id,
       NULLIF(product_category_name, ''),
       NULLIF(product_name_lenght, '')::numeric::int,
       NULLIF(product_description_lenght, '')::numeric::int,
       NULLIF(product_photos_qty, '')::numeric::int,
       NULLIF(product_weight_g, '')::numeric::int,
       NULLIF(product_length_cm, '')::numeric::int,
       NULLIF(product_height_cm, '')::numeric::int,
       NULLIF(product_width_cm, '')::numeric::int,
       20 + abs(hashtext(product_id)) % 181          -- deterministic demo stock 20..200
FROM staging.products;

-- 7. ORDERS
INSERT INTO orders (order_id, customer_id, order_status, purchase_ts, approved_at,
                    delivered_carrier_date, delivered_customer_date, estimated_delivery_date)
SELECT order_id, customer_id, order_status,
       order_purchase_timestamp::timestamp,
       NULLIF(order_approved_at, '')::timestamp,
       NULLIF(order_delivered_carrier_date, '')::timestamp,
       NULLIF(order_delivered_customer_date, '')::timestamp,
       order_estimated_delivery_date::timestamp
FROM staging.orders;

-- 8. ORDER_ITEM
INSERT INTO order_item (order_id, order_item_id, product_id, seller_id,
                        shipping_limit_date, price, freight_value)
SELECT order_id, order_item_id::int, product_id, seller_id,
       shipping_limit_date::timestamp, price::numeric, freight_value::numeric
FROM staging.order_items;

-- 9. PAYMENT_TYPE lookup and PAYMENT
INSERT INTO payment_type (payment_type, description) VALUES
 ('credit_card', 'Credit card, can be split into installments'),
 ('boleto',      'Boleto bancario (bank payment slip)'),
 ('voucher',     'Store voucher / gift card'),
 ('debit_card',  'Debit card'),
 ('not_defined', 'Payment method not recorded');

INSERT INTO payment (order_id, payment_sequential, payment_type, installments, payment_value)
SELECT order_id, payment_sequential::int, payment_type,
       payment_installments::int, payment_value::numeric
FROM staging.payments;

-- 10. REVIEW (PK is (review_id, order_id) because review_id repeats)
INSERT INTO review (review_id, order_id, review_score, comment_title, comment_message,
                    creation_date, answer_ts)
SELECT review_id, order_id, review_score::int,
       NULLIF(btrim(review_comment_title), ''),
       NULLIF(btrim(review_comment_message), ''),
       review_creation_date::timestamp,
       NULLIF(review_answer_timestamp, '')::timestamp
FROM staging.reviews;

COMMIT;

-- Row counts after load
SELECT 'state' AS table_name, COUNT(*) AS row_count FROM state
UNION ALL SELECT 'zip_code', COUNT(*) FROM zip_code
UNION ALL SELECT 'customer', COUNT(*) FROM customer
UNION ALL SELECT 'customer_account', COUNT(*) FROM customer_account
UNION ALL SELECT 'seller', COUNT(*) FROM seller
UNION ALL SELECT 'category', COUNT(*) FROM category
UNION ALL SELECT 'product', COUNT(*) FROM product
UNION ALL SELECT 'orders', COUNT(*) FROM orders
UNION ALL SELECT 'order_item', COUNT(*) FROM order_item
UNION ALL SELECT 'payment', COUNT(*) FROM payment
UNION ALL SELECT 'review', COUNT(*) FROM review;

-- Orphan check: every query below must return 0
SELECT 'items without product' AS check_name, COUNT(*) AS problems
FROM order_item oi LEFT JOIN product p USING (product_id) WHERE p.product_id IS NULL
UNION ALL
SELECT 'orders without customer', COUNT(*)
FROM orders o LEFT JOIN customer_account c USING (customer_id) WHERE c.customer_id IS NULL;

ANALYZE;
