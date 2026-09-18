-- =====================================================================
-- 01_schema.sql  --  DDL for the Olist E-Commerce & Order Management DB
-- Every table below is in BCNF (see docs / normalization section).
-- Re-runnable: drops and recreates everything in schema "public".
-- =====================================================================
SET client_min_messages = warning;

DROP VIEW IF EXISTS v_order_features, v_order_details, v_seller_performance, v_monthly_sales,
     v_customer_public, v_data_quality, v_sp_customers, v_high_risk_orders CASCADE;
DROP MATERIALIZED VIEW IF EXISTS mv_order_features, mv_seller_delivery_history CASCADE;
DROP TABLE IF EXISTS ml_prediction, ml_model, order_status_log, review, payment,
     payment_type, order_item, orders, product, category, seller,
     customer_account, customer, zip_code, state, app_user CASCADE;

CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- bcrypt password hashing (security demo)

-- ---------------------------------------------------------------------
-- Lookup / location tables
-- ---------------------------------------------------------------------
CREATE TABLE state (
    state_code  CHAR(2)      PRIMARY KEY,
    state_name  VARCHAR(40)  NOT NULL UNIQUE,          -- candidate key
    region      VARCHAR(15)  NOT NULL
        CHECK (region IN ('North','Northeast','Central-West','Southeast','South'))
);

CREATE TABLE zip_code (
    zip_prefix  INTEGER      PRIMARY KEY CHECK (zip_prefix BETWEEN 0 AND 99999),
    city        VARCHAR(60)  NOT NULL,
    state_code  CHAR(2)      NOT NULL REFERENCES state(state_code),
    lat         NUMERIC(9,6) CHECK (lat BETWEEN -34 AND 6),
    lng         NUMERIC(9,6) CHECK (lng BETWEEN -74 AND -34)
);

-- ---------------------------------------------------------------------
-- Customers (person vs per-order account) and sellers
-- ---------------------------------------------------------------------
CREATE TABLE customer (
    customer_unique_id CHAR(32) PRIMARY KEY
);

CREATE TABLE customer_account (
    customer_id        CHAR(32) PRIMARY KEY,
    customer_unique_id CHAR(32) NOT NULL REFERENCES customer(customer_unique_id)
                                ON DELETE CASCADE,
    zip_prefix         INTEGER  NOT NULL REFERENCES zip_code(zip_prefix)
);

CREATE TABLE seller (
    seller_id  CHAR(32) PRIMARY KEY,
    zip_prefix INTEGER  NOT NULL REFERENCES zip_code(zip_prefix)
);
