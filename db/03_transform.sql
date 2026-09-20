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
