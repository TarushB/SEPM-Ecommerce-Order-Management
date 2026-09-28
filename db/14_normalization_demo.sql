-- =====================================================================
-- 14_normalization_demo.sql  --  why the schema is decomposed.
-- Builds the unnormalized "one wide table" from the real data in a
-- temporary table, shows the anomalies, then shows the same facts
-- stored once in the normalized schema.
-- =====================================================================

-- The flat relation a spreadsheet would give (1NF: one row per order line)
CREATE TEMP TABLE order_flat AS
SELECT o.order_id, oi.order_item_id, o.order_status, o.purchase_ts,
       ca.customer_id, ca.customer_unique_id, cz.zip_prefix AS customer_zip,
       cz.city AS customer_city, cz.state_code AS customer_state,
       p.product_id, p.category_name, c.category_name_en,
       s.seller_id, sz.city AS seller_city, sz.state_code AS seller_state,
       oi.price, oi.freight_value
FROM orders o
JOIN order_item oi       ON oi.order_id = o.order_id
JOIN customer_account ca ON ca.customer_id = o.customer_id
JOIN zip_code cz         ON cz.zip_prefix = ca.zip_prefix
JOIN product p           ON p.product_id = oi.product_id
LEFT JOIN category c     ON c.category_name = p.category_name
JOIN seller s            ON s.seller_id = oi.seller_id
JOIN zip_code sz         ON sz.zip_prefix = s.zip_prefix;

SELECT COUNT(*) AS flat_rows FROM order_flat;

\echo ----- Redundancy: the same city/state repeated for every line -----
SELECT customer_city, customer_state, COUNT(*) AS times_stored
FROM order_flat GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 5;

\echo ----- 2NF violation: order_status depends on order_id only, not on (order_id, order_item_id) -----
SELECT order_id, COUNT(*) AS lines, COUNT(DISTINCT order_status) AS distinct_status
FROM order_flat GROUP BY order_id HAVING COUNT(*) > 5 ORDER BY lines DESC LIMIT 5;

\echo ----- 3NF violation: product_id -> category_name -> category_name_en (transitive) -----
SELECT category_name, category_name_en, COUNT(*) AS copies
FROM order_flat WHERE category_name IS NOT NULL GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 5;

\echo ----- UPDATE anomaly: renaming one category touches thousands of rows -----
BEGIN;
UPDATE order_flat SET category_name_en = 'bed_bath_and_table' WHERE category_name = 'cama_mesa_banho';
ROLLBACK;
\echo   ...while the normalized schema changes exactly one row:
BEGIN;
UPDATE category SET category_name_en = 'bed_bath_and_table' WHERE category_name = 'cama_mesa_banho';
ROLLBACK;

\echo ----- INSERT anomaly: a new category with no sales cannot exist in the flat table -----
\echo   (it would need a fake order_id); in the normalized schema it is one INSERT into category.

\echo ----- DELETE anomaly: deleting a seller's only order line loses the seller's city -----
SELECT seller_id, seller_city, COUNT(*) AS lines FROM order_flat
GROUP BY 1, 2 HAVING COUNT(*) = 1 LIMIT 3;

\echo ----- Checking functional dependencies on real data -----
\echo zip_prefix -> city, state holds in zip_code by construction (PRIMARY KEY):
SELECT COUNT(*) AS zip_rows, COUNT(DISTINCT zip_prefix) AS distinct_zip FROM zip_code;
\echo but the raw customer file violated it for some prefixes (two spellings of a city):
SELECT COUNT(*) AS violating_prefixes FROM (
    SELECT customer_zip_code_prefix FROM staging.customers
    GROUP BY 1 HAVING COUNT(DISTINCT customer_city) > 1) x;
\echo review_id alone is NOT a key (it repeats); (review_id, order_id) is:
SELECT COUNT(*) - COUNT(DISTINCT review_id) AS repeated_review_ids,
       COUNT(*) - COUNT(DISTINCT (review_id, order_id)) AS repeated_pk
FROM review;
\echo category_name <-> category_name_en: both are candidate keys (BCNF holds)
SELECT COUNT(*) AS rows, COUNT(DISTINCT category_name) AS pt, COUNT(DISTINCT category_name_en) AS en FROM category;
