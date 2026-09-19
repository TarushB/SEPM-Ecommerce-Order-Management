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

-- ---------------------------------------------------------------------
-- Catalogue
-- ---------------------------------------------------------------------
CREATE TABLE category (
    category_name    VARCHAR(60) PRIMARY KEY,
    category_name_en VARCHAR(60) NOT NULL UNIQUE          -- candidate key
);

CREATE TABLE product (
    product_id         CHAR(32) PRIMARY KEY,
    category_name      VARCHAR(60) REFERENCES category(category_name)
                                   ON UPDATE CASCADE ON DELETE RESTRICT,
    name_length        SMALLINT CHECK (name_length >= 0),
    description_length INTEGER  CHECK (description_length >= 0),
    photos_qty         SMALLINT CHECK (photos_qty >= 0),
    weight_g           INTEGER  CHECK (weight_g >= 0),
    length_cm          SMALLINT CHECK (length_cm >= 0),
    height_cm          SMALLINT CHECK (height_cm >= 0),
    width_cm           SMALLINT CHECK (width_cm >= 0),
    stock_qty          INTEGER  NOT NULL DEFAULT 50 CHECK (stock_qty >= 0)  -- added for transaction/concurrency demos
);

-- ---------------------------------------------------------------------
-- Orders and their weak entities
-- ---------------------------------------------------------------------
CREATE TABLE orders (
    order_id                CHAR(32)    PRIMARY KEY,
    customer_id             CHAR(32)    NOT NULL REFERENCES customer_account(customer_id),
    order_status            VARCHAR(12) NOT NULL
        CHECK (order_status IN ('created','approved','invoiced','processing',
                                'shipped','delivered','canceled','unavailable')),
    purchase_ts             TIMESTAMP   NOT NULL,
    approved_at             TIMESTAMP,
    delivered_carrier_date  TIMESTAMP,
    delivered_customer_date TIMESTAMP,
    estimated_delivery_date TIMESTAMP   NOT NULL,
    CONSTRAINT chk_approved_after_purchase  CHECK (approved_at IS NULL OR approved_at >= purchase_ts),
    CONSTRAINT chk_delivered_after_purchase CHECK (delivered_customer_date IS NULL OR delivered_customer_date >= purchase_ts),
    CONSTRAINT chk_estimate_after_purchase  CHECK (estimated_delivery_date >= purchase_ts)
);

CREATE TABLE order_item (
    order_id            CHAR(32)      NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    order_item_id       SMALLINT      NOT NULL CHECK (order_item_id >= 1),
    product_id          CHAR(32)      NOT NULL REFERENCES product(product_id) ON DELETE RESTRICT,
    seller_id           CHAR(32)      NOT NULL REFERENCES seller(seller_id)   ON DELETE RESTRICT,
    shipping_limit_date TIMESTAMP,
    price               NUMERIC(10,2) NOT NULL CHECK (price > 0),
    freight_value       NUMERIC(10,2) NOT NULL CHECK (freight_value >= 0),
    PRIMARY KEY (order_id, order_item_id)
);

CREATE TABLE payment_type (
    payment_type VARCHAR(15) PRIMARY KEY,
    description  VARCHAR(80) NOT NULL
);

CREATE TABLE payment (
    order_id           CHAR(32)      NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    payment_sequential SMALLINT      NOT NULL CHECK (payment_sequential >= 1),
    payment_type       VARCHAR(15)   NOT NULL REFERENCES payment_type(payment_type),
    installments       SMALLINT      NOT NULL DEFAULT 1 CHECK (installments >= 0),
    payment_value      NUMERIC(10,2) NOT NULL CHECK (payment_value >= 0),
    PRIMARY KEY (order_id, payment_sequential)
);

CREATE TABLE review (
    review_id       CHAR(32)  NOT NULL,
    order_id        CHAR(32)  NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    review_score    SMALLINT  NOT NULL CHECK (review_score BETWEEN 1 AND 5),
    comment_title   TEXT,
    comment_message TEXT,
    creation_date   TIMESTAMP NOT NULL,
    answer_ts       TIMESTAMP,
    PRIMARY KEY (review_id, order_id)          -- review_id alone repeats (814 cases)
);
