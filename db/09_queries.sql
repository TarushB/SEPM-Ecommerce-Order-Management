-- =====================================================================
-- 09_queries.sql  --  demonstration queries (generated from backend/queries.py)
-- Parameters are filled with their default values.
-- =====================================================================

-- Q1  [INNER JOIN (5 tables)]  Order lines with product category and seller city
\echo Q1: Order lines with product category and seller city
SELECT o.order_id, o.purchase_ts::date AS purchased, o.order_status,
       c.category_name_en AS category, oi.price, oi.freight_value,
       sz.city AS seller_city, sz.state_code AS seller_state
FROM orders o
JOIN order_item oi ON oi.order_id = o.order_id
JOIN product p     ON p.product_id = oi.product_id
JOIN category c    ON c.category_name = p.category_name
JOIN seller s      ON s.seller_id = oi.seller_id
JOIN zip_code sz   ON sz.zip_prefix = s.zip_prefix
WHERE sz.state_code = 'SP'
ORDER BY o.purchase_ts DESC
LIMIT 50;

-- Q2  [LEFT JOIN + IS NULL (anti-join)]  Delivered orders that never received a review
\echo Q2: Delivered orders that never received a review
SELECT o.order_id, o.purchase_ts::date AS purchased, o.delivered_customer_date::date AS delivered
FROM orders o
LEFT JOIN review r ON r.order_id = o.order_id
WHERE r.order_id IS NULL
  AND o.order_status = 'delivered'
ORDER BY o.purchase_ts DESC
LIMIT 50;

-- Q3  [SELF JOIN]  Category pairs bought together in the same order
\echo Q3: Category pairs bought together in the same order
SELECT c1.category_name_en AS category_a, c2.category_name_en AS category_b,
       COUNT(DISTINCT a.order_id) AS orders_together
FROM order_item a
JOIN order_item b ON b.order_id = a.order_id AND b.order_item_id > a.order_item_id
JOIN product pa   ON pa.product_id = a.product_id
JOIN product pb   ON pb.product_id = b.product_id
JOIN category c1  ON c1.category_name = pa.category_name
JOIN category c2  ON c2.category_name = pb.category_name
WHERE pa.category_name < pb.category_name
GROUP BY c1.category_name_en, c2.category_name_en
ORDER BY orders_together DESC
LIMIT 20;

-- Q4  [Aggregates + GROUP BY]  Monthly orders, revenue and average ticket
\echo Q4: Monthly orders, revenue and average ticket
SELECT to_char(date_trunc('month', o.purchase_ts), 'YYYY-MM') AS month,
       COUNT(DISTINCT o.order_id)                  AS orders,
       ROUND(SUM(oi.price), 2)                     AS revenue,
       ROUND(SUM(oi.price) / COUNT(DISTINCT o.order_id), 2) AS avg_ticket,
       ROUND(AVG(oi.freight_value), 2)             AS avg_freight
FROM orders o
JOIN order_item oi ON oi.order_id = o.order_id
WHERE o.order_status NOT IN ('canceled', 'unavailable')
GROUP BY 1
ORDER BY 1;

-- Q5  [GROUP BY + HAVING]  Busy sellers with poor ratings
\echo Q5: Busy sellers with poor ratings
SELECT s.seller_id, z.city, z.state_code,
       COUNT(DISTINCT oi.order_id)    AS orders,
       ROUND(AVG(r.review_score), 2)  AS avg_rating
FROM seller s
JOIN zip_code z    ON z.zip_prefix = s.zip_prefix
JOIN order_item oi ON oi.seller_id = s.seller_id
JOIN review r      ON r.order_id = oi.order_id
GROUP BY s.seller_id, z.city, z.state_code
HAVING COUNT(DISTINCT oi.order_id) > 50
   AND AVG(r.review_score) < 3.8
ORDER BY avg_rating;

-- Q6  [Subquery with IN]  Customers who bought from the #1 revenue category
\echo Q6: Customers who bought from the #1 revenue category
SELECT ca.customer_unique_id, z.city, z.state_code
FROM customer_account ca
JOIN zip_code z ON z.zip_prefix = ca.zip_prefix
WHERE ca.customer_id IN (
    SELECT o.customer_id
    FROM orders o
    JOIN order_item oi ON oi.order_id = o.order_id
    JOIN product p     ON p.product_id = oi.product_id
    WHERE p.category_name = (
        SELECT p2.category_name
        FROM order_item oi2 JOIN product p2 ON p2.product_id = oi2.product_id
        WHERE p2.category_name IS NOT NULL
        GROUP BY p2.category_name
        ORDER BY SUM(oi2.price) DESC
        LIMIT 1))
LIMIT 50;

-- Q7  [Correlated subqueries (in WHERE and SELECT)]  Loyal customers: people with 3 or more orders and their total spend
\echo Q7: Loyal customers: people with 3 or more orders and their total spend
SELECT c.customer_unique_id,
       (SELECT COUNT(*) FROM customer_account ca
         WHERE ca.customer_unique_id = c.customer_unique_id)             AS orders,
       (SELECT ROUND(SUM(oi.price + oi.freight_value), 2)
          FROM customer_account ca
          JOIN orders o      ON o.customer_id = ca.customer_id
          JOIN order_item oi ON oi.order_id = o.order_id
         WHERE ca.customer_unique_id = c.customer_unique_id)             AS total_spend
FROM customer c
WHERE (SELECT COUNT(*) FROM customer_account ca
        WHERE ca.customer_unique_id = c.customer_unique_id) >= 3   -- correlated on c
ORDER BY orders DESC, total_spend DESC;

-- Q8  [EXISTS / NOT EXISTS]  Sellers with at least one 1-star review but no canceled orders
\echo Q8: Sellers with at least one 1-star review but no canceled orders
SELECT s.seller_id, fn_seller_rating(s.seller_id) AS avg_rating
FROM seller s
WHERE EXISTS (SELECT 1 FROM order_item oi JOIN review r ON r.order_id = oi.order_id
              WHERE oi.seller_id = s.seller_id AND r.review_score = 1)
  AND NOT EXISTS (SELECT 1 FROM order_item oi JOIN orders o ON o.order_id = oi.order_id
                  WHERE oi.seller_id = s.seller_id AND o.order_status = 'canceled')
ORDER BY avg_rating
LIMIT 50;

-- Q9  [Derived table (subquery in FROM)]  States whose average delivery time beats the national average
\echo Q9: States whose average delivery time beats the national average
SELECT t.state_code, t.orders, t.avg_days,
       ROUND((SELECT AVG(EXTRACT(EPOCH FROM delivered_customer_date - purchase_ts) / 86400)
                FROM orders WHERE delivered_customer_date IS NOT NULL), 1) AS national_avg
FROM (
    SELECT z.state_code, COUNT(*) AS orders,
           ROUND(AVG(EXTRACT(EPOCH FROM o.delivered_customer_date - o.purchase_ts) / 86400), 1) AS avg_days
    FROM orders o
    JOIN customer_account ca ON ca.customer_id = o.customer_id
    JOIN zip_code z          ON z.zip_prefix = ca.zip_prefix
    WHERE o.delivered_customer_date IS NOT NULL
    GROUP BY z.state_code
) t
WHERE t.avg_days < (SELECT AVG(EXTRACT(EPOCH FROM delivered_customer_date - purchase_ts) / 86400)
                      FROM orders WHERE delivered_customer_date IS NOT NULL)
ORDER BY t.avg_days;

-- Q10  [Scalar subqueries in SELECT + stored function]  Orders with item count, order total and amount paid
\echo Q10: Orders with item count, order total and amount paid
SELECT o.order_id, o.order_status,
       (SELECT COUNT(*) FROM order_item oi WHERE oi.order_id = o.order_id) AS items,
       fn_order_total(o.order_id)                                          AS order_total,
       (SELECT SUM(payment_value) FROM payment p WHERE p.order_id = o.order_id) AS paid
FROM orders o
ORDER BY o.purchase_ts DESC
LIMIT 50;

-- Q11  [UNION / INTERSECT / EXCEPT]  Which states have customers, sellers, or both
\echo Q11: Which states have customers, sellers, or both
(SELECT z.state_code, 'customers and sellers' AS presence
   FROM customer_account ca JOIN zip_code z ON z.zip_prefix = ca.zip_prefix
 INTERSECT
 SELECT z.state_code, 'customers and sellers'
   FROM seller s JOIN zip_code z ON z.zip_prefix = s.zip_prefix)
UNION ALL
(SELECT z.state_code, 'customers only'
   FROM customer_account ca JOIN zip_code z ON z.zip_prefix = ca.zip_prefix
 EXCEPT
 SELECT z.state_code, 'customers only'
   FROM seller s JOIN zip_code z ON z.zip_prefix = s.zip_prefix)
ORDER BY presence, state_code;

-- Q12  [CASE inside aggregates]  On-time vs late deliveries and rating by customer state
\echo Q12: On-time vs late deliveries and rating by customer state
SELECT z.state_code,
       COUNT(*) AS delivered,
       SUM(CASE WHEN o.delivered_customer_date <= o.estimated_delivery_date THEN 1 ELSE 0 END) AS on_time,
       SUM(CASE WHEN o.delivered_customer_date >  o.estimated_delivery_date THEN 1 ELSE 0 END) AS late,
       ROUND(100.0 * AVG(CASE WHEN o.delivered_customer_date > o.estimated_delivery_date
                              THEN 1 ELSE 0 END), 1) AS late_pct,
       ROUND(AVG(r.review_score), 2) AS avg_rating
FROM orders o
JOIN customer_account ca ON ca.customer_id = o.customer_id
JOIN zip_code z          ON z.zip_prefix = ca.zip_prefix
LEFT JOIN review r       ON r.order_id = o.order_id
WHERE o.delivered_customer_date IS NOT NULL
GROUP BY z.state_code
ORDER BY late_pct DESC;

-- Q13  [Window functions (LAG, running SUM, RANK)]  Month-over-month revenue growth, running total and rank
\echo Q13: Month-over-month revenue growth, running total and rank
WITH monthly AS (
    SELECT date_trunc('month', o.purchase_ts)::date AS month, SUM(oi.price) AS revenue
    FROM orders o JOIN order_item oi ON oi.order_id = o.order_id
    WHERE o.purchase_ts >= '2017-01-01' AND o.purchase_ts < '2018-09-01'
    GROUP BY 1
)
SELECT to_char(month, 'YYYY-MM') AS month,
       ROUND(revenue, 0) AS revenue,
       ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY month))
             / LAG(revenue) OVER (ORDER BY month), 1)            AS growth_pct,
       ROUND(SUM(revenue) OVER (ORDER BY month), 0)              AS running_total,
       RANK() OVER (ORDER BY revenue DESC)                       AS revenue_rank
FROM monthly
ORDER BY month;

-- Q13b  [Window function: RANK() OVER (PARTITION BY ...)]  Top 3 best-selling products in each of the 5 biggest categories
\echo Q13b: Top 3 best-selling products in each of the 5 biggest categories
WITH sales AS (
    SELECT c.category_name_en AS category, oi.product_id,
           COUNT(*) AS units, ROUND(SUM(oi.price), 2) AS revenue
    FROM order_item oi
    JOIN product p  ON p.product_id = oi.product_id
    JOIN category c ON c.category_name = p.category_name
    GROUP BY c.category_name_en, oi.product_id
), ranked AS (
    SELECT *, RANK() OVER (PARTITION BY category ORDER BY units DESC) AS rank_in_category,
           SUM(units) OVER (PARTITION BY category) AS category_units
    FROM sales
)
SELECT category, rank_in_category, product_id, units, revenue
FROM ranked
WHERE rank_in_category <= 3
  AND category IN (SELECT category FROM sales GROUP BY category ORDER BY SUM(units) DESC LIMIT 5)
ORDER BY category, rank_in_category;

-- Q14  [CTE + recursive CTE]  Customer lifetime value with every month of 2017 (zero-sale months included)
\echo Q14: Customer lifetime value with every month of 2017 (zero-sale months included)
WITH RECURSIVE months(m) AS (
    SELECT DATE '2017-01-01'
    UNION ALL
    SELECT (m + INTERVAL '1 month')::date FROM months WHERE m < DATE '2017-12-01'
), clv AS (
    SELECT ca.customer_unique_id,
           COUNT(DISTINCT o.order_id) AS orders,
           SUM(oi.price + oi.freight_value) AS lifetime_value,
           MIN(date_trunc('month', o.purchase_ts))::date AS first_month
    FROM customer_account ca
    JOIN orders o      ON o.customer_id = ca.customer_id
    JOIN order_item oi ON oi.order_id = o.order_id
    GROUP BY ca.customer_unique_id
)
SELECT to_char(months.m, 'YYYY-MM') AS month,
       COUNT(clv.customer_unique_id)            AS new_customers,
       ROUND(COALESCE(AVG(clv.lifetime_value), 0), 2) AS avg_lifetime_value,
       COALESCE(SUM(CASE WHEN clv.orders > 1 THEN 1 ELSE 0 END), 0) AS repeat_customers
FROM months
LEFT JOIN clv ON clv.first_month = months.m
GROUP BY months.m
ORDER BY months.m;

-- Q15  [ALL / ANY]  Products heavier than every telephony product
\echo Q15: Products heavier than every telephony product
SELECT p.product_id, c.category_name_en AS category, p.weight_g
FROM product p
JOIN category c ON c.category_name = p.category_name
WHERE p.weight_g > ALL (SELECT weight_g FROM product
                        WHERE category_name = 'telefonia' AND weight_g IS NOT NULL)
ORDER BY p.weight_g DESC
LIMIT 50;

-- Q16  [Full-text search (GIN index)]  Reviews mentioning a word (Portuguese stemming)
\echo Q16: Reviews mentioning a word (Portuguese stemming)
SELECT r.order_id, r.review_score, r.comment_title, r.comment_message
FROM review r
WHERE to_tsvector('portuguese', coalesce(r.comment_title,'') || ' ' || coalesce(r.comment_message,''))
      @@ plainto_tsquery('portuguese', 'atraso')
ORDER BY r.creation_date DESC
LIMIT 50;
