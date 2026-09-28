-- =====================================================================
-- 12_ddl_dml_demo.sql  --  ALTER / RENAME / TRUNCATE / DROP and hand-written
-- INSERT / UPDATE / DELETE. Everything runs inside a transaction that is
-- rolled back at the end, so the real database is untouched.
-- (PostgreSQL DDL is transactional, which is itself worth pointing out.)
-- =====================================================================
BEGIN;

-- DDL -----------------------------------------------------------------
ALTER TABLE customer ADD COLUMN email VARCHAR(120);
ALTER TABLE customer ADD CONSTRAINT chk_email CHECK (email LIKE '%_@_%._%');
ALTER TABLE category RENAME COLUMN category_name_en TO name_english;
ALTER TABLE category RENAME COLUMN name_english TO category_name_en;
CREATE TABLE promo_code (
    code        VARCHAR(20) PRIMARY KEY,
    discount    NUMERIC(4,2) NOT NULL CHECK (discount > 0 AND discount < 1),
    valid_until DATE NOT NULL
);
ALTER TABLE promo_code RENAME TO coupon;
\d coupon

-- DML -----------------------------------------------------------------
INSERT INTO category(category_name, category_name_en) VALUES ('jogos_de_tabuleiro', 'board_games');
INSERT INTO product(product_id, category_name, name_length, description_length, photos_qty,
                    weight_g, length_cm, height_cm, width_cm, stock_qty)
VALUES ('demo_product_0000000000000000001', 'jogos_de_tabuleiro', 30, 400, 3, 900, 30, 8, 30, 25);

INSERT INTO coupon VALUES ('WELCOME10', 0.10, DATE '2026-12-31'), ('BLACKFRIDAY', 0.25, DATE '2026-11-30');

UPDATE customer SET email = 'buyer' || left(customer_unique_id, 6) || '@example.com'
WHERE customer_unique_id IN (SELECT customer_unique_id FROM customer ORDER BY 1 LIMIT 3);

UPDATE product SET stock_qty = stock_qty + 10
WHERE category_name = 'jogos_de_tabuleiro';

-- INSERT ... SELECT and UPDATE ... FROM (joins inside DML)
CREATE TEMP TABLE sp_big_orders AS
SELECT o.order_id, fn_order_total(o.order_id) AS total
FROM orders o JOIN customer_account ca USING (customer_id)
JOIN zip_code z USING (zip_prefix)
WHERE z.state_code = 'SP' AND fn_order_total(o.order_id) > 2000;
SELECT COUNT(*) AS sp_orders_over_2000 FROM sp_big_orders;

UPDATE product p SET stock_qty = p.stock_qty + 1
FROM order_item oi WHERE oi.product_id = p.product_id AND oi.order_id IN (SELECT order_id FROM sp_big_orders);

DELETE FROM coupon WHERE valid_until < DATE '2026-12-01';
DELETE FROM product WHERE product_id = 'demo_product_0000000000000000001';
DELETE FROM category WHERE category_name = 'jogos_de_tabuleiro';

-- FK protects referenced data: this product has been sold, so DELETE fails
SAVEPOINT s1;
DELETE FROM product WHERE product_id = '4244733e06e7ecb4970a6e2683c13e61';
ROLLBACK TO SAVEPOINT s1;

TRUNCATE coupon;
DROP TABLE coupon;
ALTER TABLE customer DROP COLUMN email;

ROLLBACK;   -- undo everything above
