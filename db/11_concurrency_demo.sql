-- =====================================================================
-- 11_concurrency_demo.sql  --  isolation and locking (TWO sessions)
-- Open two psql windows:  psql -U postgres -d olist
-- Paste the lines marked [A] in window A and [B] in window B, in order.
-- The product used:  4244733e06e7ecb4970a6e2683c13e61
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. LOST UPDATE and how SELECT ... FOR UPDATE prevents it
-- ---------------------------------------------------------------------
-- [A] BEGIN;
-- [A] SELECT stock_qty FROM product WHERE product_id = '4244733e06e7ecb4970a6e2683c13e61';   -- say 100
-- [B] BEGIN;
-- [B] SELECT stock_qty FROM product WHERE product_id = '4244733e06e7ecb4970a6e2683c13e61';   -- also 100
-- [A] UPDATE product SET stock_qty = 99 WHERE product_id = '4244733e06e7ecb4970a6e2683c13e61';  -- app computed 100-1
-- [A] COMMIT;
-- [B] UPDATE product SET stock_qty = 99 WHERE product_id = '4244733e06e7ecb4970a6e2683c13e61';  -- also 100-1
-- [B] COMMIT;
--     Two sales, but stock only dropped by 1: A's update was LOST.
--
-- Fix: lock the row when reading it.
-- [A] BEGIN;
-- [A] SELECT stock_qty FROM product WHERE product_id = '4244733e06e7ecb4970a6e2683c13e61' FOR UPDATE;
-- [B] BEGIN;
-- [B] SELECT stock_qty FROM product WHERE product_id = '4244733e06e7ecb4970a6e2683c13e61' FOR UPDATE;  -- WAITS
-- [A] UPDATE product SET stock_qty = stock_qty - 1 WHERE product_id = '4244733e06e7ecb4970a6e2683c13e61';
-- [A] COMMIT;                                     -- B now continues and sees the new value
-- [B] UPDATE product SET stock_qty = stock_qty - 1 WHERE product_id = '4244733e06e7ecb4970a6e2683c13e61';
-- [B] COMMIT;                                     -- both decrements applied
-- (Writing "stock_qty = stock_qty - 1" in one statement, as trg_reduce_stock does, is also safe.)

-- ---------------------------------------------------------------------
-- 2. DIRTY READ never happens in PostgreSQL
-- ---------------------------------------------------------------------
-- [A] BEGIN;
-- [A] UPDATE product SET stock_qty = 0 WHERE product_id = '4244733e06e7ecb4970a6e2683c13e61';
-- [B] SELECT stock_qty FROM product WHERE product_id = '4244733e06e7ecb4970a6e2683c13e61';  -- old value, not 0
-- [A] ROLLBACK;
--     Even READ UNCOMMITTED behaves like READ COMMITTED in PostgreSQL (MVCC).

-- ---------------------------------------------------------------------
-- 3. NON-REPEATABLE READ: READ COMMITTED vs REPEATABLE READ
-- ---------------------------------------------------------------------
-- [A] BEGIN ISOLATION LEVEL READ COMMITTED;
-- [A] SELECT stock_qty FROM product WHERE product_id = '4244733e06e7ecb4970a6e2683c13e61';   -- e.g. 98
-- [B] UPDATE product SET stock_qty = stock_qty + 5 WHERE product_id = '4244733e06e7ecb4970a6e2683c13e61';  -- autocommit
-- [A] SELECT stock_qty FROM product WHERE product_id = '4244733e06e7ecb4970a6e2683c13e61';   -- 103: value changed inside A
-- [A] COMMIT;
--
-- [A] BEGIN ISOLATION LEVEL REPEATABLE READ;
-- [A] SELECT stock_qty FROM product WHERE product_id = '4244733e06e7ecb4970a6e2683c13e61';   -- 103
-- [B] UPDATE product SET stock_qty = stock_qty - 5 WHERE product_id = '4244733e06e7ecb4970a6e2683c13e61';
-- [A] SELECT stock_qty FROM product WHERE product_id = '4244733e06e7ecb4970a6e2683c13e61';   -- still 103 (snapshot)
-- [A] UPDATE product SET stock_qty = stock_qty - 1 WHERE product_id = '4244733e06e7ecb4970a6e2683c13e61';
--     ERROR: could not serialize access due to concurrent update  -> the app must retry
-- [A] ROLLBACK;

-- ---------------------------------------------------------------------
-- 4. SERIALIZABLE: write skew is detected
--    Rule: "a seller may have at most one order in status 'processing'".
-- ---------------------------------------------------------------------
-- [A] BEGIN ISOLATION LEVEL SERIALIZABLE;
-- [A] SELECT COUNT(*) FROM orders WHERE order_status = 'processing';
-- [B] BEGIN ISOLATION LEVEL SERIALIZABLE;
-- [B] SELECT COUNT(*) FROM orders WHERE order_status = 'processing';
-- [A] UPDATE orders SET order_status = 'processing' WHERE order_id = (SELECT order_id FROM orders WHERE order_status='invoiced' ORDER BY order_id LIMIT 1);
-- [B] UPDATE orders SET order_status = 'processing' WHERE order_id = (SELECT order_id FROM orders WHERE order_status='invoiced' ORDER BY order_id DESC LIMIT 1);
-- [A] COMMIT;
-- [B] COMMIT;   -- ERROR 40001: could not serialize access due to read/write dependencies
--     (run  ROLLBACK;  in both windows afterwards if needed, then undo A's change:
--      UPDATE is one-way by trigger, so restore with a superuser:
--      ALTER TABLE orders DISABLE TRIGGER trg_validate_status_transition; ... ENABLE ...)

-- ---------------------------------------------------------------------
-- 5. DEADLOCK: opposite lock order
-- ---------------------------------------------------------------------
-- [A] BEGIN;
-- [A] UPDATE product SET stock_qty = stock_qty WHERE product_id = '4244733e06e7ecb4970a6e2683c13e61';
-- [B] BEGIN;
-- [B] UPDATE product SET stock_qty = stock_qty WHERE product_id = 'e5f2d52b802189ee658865ca93d83a8f';
-- [A] UPDATE product SET stock_qty = stock_qty WHERE product_id = 'e5f2d52b802189ee658865ca93d83a8f';   -- waits for B
-- [B] UPDATE product SET stock_qty = stock_qty WHERE product_id = '4244733e06e7ecb4970a6e2683c13e61';   -- deadlock!
--     After ~1 s (deadlock_timeout) PostgreSQL aborts one of them: "ERROR: deadlock detected".
-- [A] ROLLBACK;  [B] ROLLBACK;
--     Prevention: always lock rows in the same order (e.g. ORDER BY product_id ... FOR UPDATE).

-- Watch locks from a third window while a demo is paused:
SELECT pid, locktype, relation::regclass AS relation, mode, granted
FROM pg_locks WHERE relation = 'product'::regclass;
SHOW default_transaction_isolation;
SHOW deadlock_timeout;
