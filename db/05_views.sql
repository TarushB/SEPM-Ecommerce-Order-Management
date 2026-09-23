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

-- Data-quality exceptions kept visible instead of silently deleted.
CREATE OR REPLACE VIEW v_data_quality AS
SELECT 'order without items' AS issue, o.order_id::text AS ref, o.order_status AS detail
FROM orders o WHERE NOT EXISTS (SELECT 1 FROM order_item oi WHERE oi.order_id = o.order_id)
UNION ALL
SELECT 'order without payment', o.order_id, o.order_status
FROM orders o WHERE NOT EXISTS (SELECT 1 FROM payment p WHERE p.order_id = o.order_id)
UNION ALL
SELECT 'handed to carrier before purchase', o.order_id, o.delivered_carrier_date::text
FROM orders o WHERE o.delivered_carrier_date < o.purchase_ts
UNION ALL
SELECT 'delivered before handed to carrier', o.order_id, o.delivered_customer_date::text
FROM orders o WHERE o.delivered_customer_date < o.delivered_carrier_date
UNION ALL
SELECT 'zip prefix without coordinates', z.zip_prefix::text, z.city
FROM zip_code z WHERE z.lat IS NULL
UNION ALL
SELECT 'payment total differs from items by > R$1', t.order_id, t.diff::text
FROM (SELECT o.order_id,
             (SELECT SUM(payment_value) FROM payment p WHERE p.order_id = o.order_id) -
             (SELECT SUM(price + freight_value) FROM order_item i WHERE i.order_id = o.order_id) AS diff
      FROM orders o) t
WHERE abs(t.diff) > 1;

-- Updatable view WITH CHECK OPTION: support staff for Sao Paulo can only
-- insert/update customer accounts whose zip prefix belongs to SP.
CREATE OR REPLACE VIEW v_sp_customers AS
SELECT ca.customer_id, ca.customer_unique_id, ca.zip_prefix
FROM customer_account ca
WHERE ca.zip_prefix IN (SELECT zip_prefix FROM zip_code WHERE state_code = 'SP')
WITH CHECK OPTION;

-- ---------------------------------------------------------------------
-- Feature view: one row per order with every ML feature that is
-- known at purchase time, plus the two labels (NULL until delivered).
-- ---------------------------------------------------------------------
-- Helper: running totals of each seller's delivered orders, in delivery
-- order. mv_order_features looks up "the last row before this purchase"
-- with one index probe instead of re-scanning the seller's history.
CREATE MATERIALIZED VIEW mv_seller_delivery_history AS
WITH seller_orders AS (
    SELECT DISTINCT oi.seller_id, o.order_id, o.delivered_customer_date AS delivered_at,
           (o.delivered_customer_date > o.estimated_delivery_date)::int AS was_late
    FROM order_item oi
    JOIN orders o ON o.order_id = oi.order_id
    WHERE o.delivered_customer_date IS NOT NULL
)
SELECT seller_id, delivered_at, order_id,
       COUNT(*)      OVER w AS cum_orders,
       SUM(was_late) OVER w AS cum_late
FROM seller_orders
WINDOW w AS (PARTITION BY seller_id ORDER BY delivered_at, order_id
             ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW);

CREATE UNIQUE INDEX ux_seller_history ON mv_seller_delivery_history(seller_id, delivered_at, order_id);

CREATE OR REPLACE VIEW v_order_features AS
WITH items AS (
    SELECT oi.order_id,
           COUNT(*)                                   AS n_items,
           COUNT(DISTINCT oi.seller_id)               AS n_sellers,
           SUM(oi.price)                              AS total_price,
           SUM(oi.freight_value)                      AS total_freight,
           SUM(COALESCE(p.weight_g, 0))               AS total_weight_g,
           SUM(COALESCE(p.length_cm::bigint * p.height_cm * p.width_cm, 0)) AS total_volume_cm3,
           MIN(oi.shipping_limit_date)                AS first_shipping_limit,
           (ARRAY_AGG(oi.seller_id ORDER BY oi.price DESC, oi.order_item_id))[1]      AS main_seller_id,
           (ARRAY_AGG(COALESCE(c.category_name_en,'unknown')
                      ORDER BY oi.price DESC, oi.order_item_id))[1]                  AS main_category
    FROM order_item oi
    JOIN product p       ON p.product_id = oi.product_id
    LEFT JOIN category c ON c.category_name = p.category_name
    GROUP BY oi.order_id
), pay AS (
    SELECT order_id,
           (ARRAY_AGG(payment_type ORDER BY payment_sequential))[1] AS payment_type,
           MAX(installments)                                         AS installments
    FROM payment GROUP BY order_id
), base AS (
    SELECT o.order_id, o.order_status, o.purchase_ts, o.estimated_delivery_date,
           o.delivered_customer_date,
           i.n_items, i.n_sellers, i.total_price, i.total_freight, i.total_weight_g,
           i.total_volume_cm3, i.first_shipping_limit, i.main_seller_id, i.main_category,
           pay.payment_type, pay.installments,
           cz.state_code AS customer_state, cs.region AS customer_region,
           sz.state_code AS seller_state,
           cz.lat AS c_lat, cz.lng AS c_lng, sz.lat AS s_lat, sz.lng AS s_lng
    FROM orders o
    JOIN items i              ON i.order_id = o.order_id
    LEFT JOIN pay             ON pay.order_id = o.order_id
    JOIN customer_account ca  ON ca.customer_id = o.customer_id
    JOIN zip_code cz          ON cz.zip_prefix = ca.zip_prefix
    JOIN state cs             ON cs.state_code = cz.state_code
    JOIN seller s             ON s.seller_id = i.main_seller_id
    JOIN zip_code sz          ON sz.zip_prefix = s.zip_prefix
)
SELECT b.order_id,
       b.order_status,
       b.purchase_ts,
       -- geography
       b.customer_state, b.customer_region, b.seller_state,
       (b.customer_state = b.seller_state)::int                          AS same_state,
       ROUND((6371 * 2 * ASIN(SQRT(
             POWER(SIN(RADIANS(b.s_lat - b.c_lat) / 2), 2) +
             COS(RADIANS(b.c_lat)) * COS(RADIANS(b.s_lat)) *
             POWER(SIN(RADIANS(b.s_lng - b.c_lng) / 2), 2))))::numeric, 1)   AS distance_km,
       -- order
       b.n_items, b.n_sellers, b.total_price, b.total_freight,
       ROUND(b.total_freight / NULLIF(b.total_price, 0), 4)              AS freight_ratio,
       COALESCE(b.payment_type, 'not_defined')                          AS payment_type,
       COALESCE(b.installments, 1)                                      AS installments,
       -- product
       b.total_weight_g, b.total_volume_cm3, b.main_category,
       -- time
       EXTRACT(MONTH FROM b.purchase_ts)::int                           AS purchase_month,
       EXTRACT(ISODOW FROM b.purchase_ts)::int                          AS purchase_dow,
       EXTRACT(HOUR FROM b.purchase_ts)::int                            AS purchase_hour,
       ROUND(EXTRACT(EPOCH FROM b.estimated_delivery_date - b.purchase_ts) / 86400, 2) AS promised_days,
       ROUND(EXTRACT(EPOCH FROM b.first_shipping_limit - b.purchase_ts) / 86400, 2)    AS ship_limit_days,
       -- seller history: only orders of this seller DELIVERED before this purchase (no leakage)
       COALESCE(sh.prior_orders, 0)                                     AS seller_prior_orders,
       sh.prior_late_rate                                               AS seller_prior_late_rate,
       -- labels
       CASE WHEN b.order_status = 'delivered' AND b.delivered_customer_date IS NOT NULL
            THEN (b.delivered_customer_date > b.estimated_delivery_date)::int END        AS is_late,
       CASE WHEN b.order_status = 'delivered' AND b.delivered_customer_date IS NOT NULL
            THEN ROUND(EXTRACT(EPOCH FROM b.delivered_customer_date - b.purchase_ts) / 86400, 2) END
                                                                        AS delivery_days
FROM base b
LEFT JOIN LATERAL (
    SELECT h.cum_orders::int                            AS prior_orders,
           ROUND(h.cum_late::numeric / h.cum_orders, 4)  AS prior_late_rate
    FROM mv_seller_delivery_history h
    WHERE h.seller_id = b.main_seller_id
      AND h.delivered_at < b.purchase_ts
    ORDER BY h.delivered_at DESC, h.order_id DESC
    LIMIT 1
) sh ON true;

-- Materialized copy for training / reporting; the plain view above answers
-- live questions about a single (possibly brand-new) order.
CREATE MATERIALIZED VIEW mv_order_features AS SELECT * FROM v_order_features;
CREATE UNIQUE INDEX ux_mv_order_features ON mv_order_features(order_id);

-- ML output joined back to business data: managers query risk with plain SQL.
CREATE OR REPLACE VIEW v_high_risk_orders AS
SELECT mp.order_id, o.order_status, o.purchase_ts, o.estimated_delivery_date,
       f.customer_state, f.seller_state, f.distance_km, f.main_category,
       mp.late_probability, mp.predicted_days, mp.model_version
FROM ml_prediction mp
JOIN orders o             ON o.order_id = mp.order_id
LEFT JOIN mv_order_features f ON f.order_id = mp.order_id
WHERE o.order_status NOT IN ('delivered','canceled','unavailable');
