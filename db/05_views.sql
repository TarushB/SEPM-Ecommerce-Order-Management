-- =====================================================================
-- 05_views.sql  --  views, an updatable view WITH CHECK OPTION and the
-- materialized view that feeds the ML model.
-- =====================================================================
SET client_min_messages = warning;

-- One row per order with the facts every screen needs.
CREATE OR REPLACE VIEW v_order_details AS
SELECT o.order_id,
       o.order_status,
       o.purchase_ts,
       o.estimated_delivery_date,
       o.delivered_customer_date,
       ca.customer_id,
       ca.customer_unique_id,
       z.city                AS customer_city,
       z.state_code          AS customer_state,
       (SELECT COUNT(*) FROM order_item oi WHERE oi.order_id = o.order_id)          AS item_count,
       (SELECT COALESCE(SUM(oi.price + oi.freight_value), 0)
          FROM order_item oi WHERE oi.order_id = o.order_id)                       AS order_total,
       (SELECT COALESCE(SUM(p.payment_value), 0)
          FROM payment p WHERE p.order_id = o.order_id)                            AS amount_paid,
       (SELECT MIN(r.review_score) FROM review r WHERE r.order_id = o.order_id)    AS review_score,
       CASE WHEN o.delivered_customer_date IS NULL THEN NULL
            ELSE o.delivered_customer_date > o.estimated_delivery_date END         AS is_late
FROM orders o
JOIN customer_account ca ON ca.customer_id = o.customer_id
JOIN zip_code z          ON z.zip_prefix   = ca.zip_prefix;

-- Seller scorecard.
CREATE OR REPLACE VIEW v_seller_performance AS
SELECT s.seller_id,
       z.city  AS seller_city,
       z.state_code AS seller_state,
       COUNT(DISTINCT oi.order_id)                    AS orders,
       SUM(oi.price)                                  AS revenue,
       ROUND(AVG(r.review_score), 2)                  AS avg_rating,
       ROUND(100.0 * AVG(CASE WHEN o.delivered_customer_date > o.estimated_delivery_date
                              THEN 1 ELSE 0 END)
             FILTER (WHERE o.delivered_customer_date IS NOT NULL), 1) AS late_pct
FROM seller s
JOIN zip_code z        ON z.zip_prefix = s.zip_prefix
LEFT JOIN order_item oi ON oi.seller_id = s.seller_id
LEFT JOIN orders o      ON o.order_id  = oi.order_id
LEFT JOIN review r      ON r.order_id  = oi.order_id
GROUP BY s.seller_id, z.city, z.state_code;

-- Monthly revenue by category (dashboard charts).
CREATE OR REPLACE VIEW v_monthly_sales AS
SELECT date_trunc('month', o.purchase_ts)::date   AS month,
       COALESCE(c.category_name_en, 'unknown')    AS category,
       COUNT(DISTINCT o.order_id)                  AS orders,
       SUM(oi.price)                               AS revenue,
       SUM(oi.freight_value)                       AS freight
FROM orders o
JOIN order_item oi   ON oi.order_id = o.order_id
JOIN product p       ON p.product_id = oi.product_id
LEFT JOIN category c ON c.category_name = p.category_name
WHERE o.order_status NOT IN ('canceled','unavailable')
GROUP BY 1, 2;

-- Privacy view: customers without exact location (granted to support role).
CREATE OR REPLACE VIEW v_customer_public AS
SELECT ca.customer_id, ca.customer_unique_id, z.city, z.state_code
FROM customer_account ca
JOIN zip_code z ON z.zip_prefix = ca.zip_prefix;
