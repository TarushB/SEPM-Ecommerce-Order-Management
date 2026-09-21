-- =====================================================================
-- 04_indexes.sql  --  secondary indexes.
-- PostgreSQL indexes PRIMARY KEY and UNIQUE columns automatically, but NOT
-- foreign-key columns, so the join columns are indexed here.
-- Prove the benefit with 13_index_demo.sql (EXPLAIN ANALYZE before/after).
-- =====================================================================
SET client_min_messages = warning;

-- B-tree indexes on foreign keys (join performance)
CREATE INDEX IF NOT EXISTS ix_order_item_product ON order_item(product_id);
CREATE INDEX IF NOT EXISTS ix_order_item_seller  ON order_item(seller_id);
CREATE INDEX IF NOT EXISTS ix_payment_order      ON payment(order_id);   -- also leading PK column; kept for clarity
CREATE INDEX IF NOT EXISTS ix_review_order       ON review(order_id);
CREATE INDEX IF NOT EXISTS ix_orders_customer    ON orders(customer_id);
CREATE INDEX IF NOT EXISTS ix_account_person     ON customer_account(customer_unique_id);
CREATE INDEX IF NOT EXISTS ix_account_zip        ON customer_account(zip_prefix);
CREATE INDEX IF NOT EXISTS ix_seller_zip         ON seller(zip_prefix);
CREATE INDEX IF NOT EXISTS ix_zip_state          ON zip_code(state_code);
CREATE INDEX IF NOT EXISTS ix_product_category   ON product(category_name);
CREATE INDEX IF NOT EXISTS ix_status_log_order   ON order_status_log(order_id);

-- Range / filter indexes
CREATE INDEX IF NOT EXISTS ix_orders_purchase_ts   ON orders(purchase_ts);
CREATE INDEX IF NOT EXISTS ix_orders_status_ts     ON orders(order_status, purchase_ts);   -- composite
CREATE INDEX IF NOT EXISTS ix_review_score         ON review(review_score);

-- Partial index: only the ~3k orders that are still open (small and fast)
CREATE INDEX IF NOT EXISTS ix_orders_open
    ON orders(purchase_ts) WHERE order_status NOT IN ('delivered','canceled','unavailable');

-- Expression index: case-insensitive category search
CREATE INDEX IF NOT EXISTS ix_category_en_lower ON category(lower(category_name_en));

-- GIN full-text index on Portuguese review comments
CREATE INDEX IF NOT EXISTS ix_review_fts
    ON review USING GIN (to_tsvector('portuguese', coalesce(comment_title,'') || ' ' || coalesce(comment_message,'')));

ANALYZE;
