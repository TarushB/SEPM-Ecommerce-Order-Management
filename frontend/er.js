// ER model of the Olist database (Mermaid syntax). Same model as the design document.
window.ER_DIAGRAM = `erDiagram
    STATE ||--o{ ZIP_CODE : contains
    ZIP_CODE ||--o{ CUSTOMER_ACCOUNT : locates
    ZIP_CODE ||--o{ SELLER : locates
    CUSTOMER ||--|{ CUSTOMER_ACCOUNT : owns
    CUSTOMER_ACCOUNT ||--o{ ORDERS : places
    ORDERS ||--o{ ORDER_ITEM : contains
    PRODUCT ||--o{ ORDER_ITEM : "sold as"
    SELLER ||--o{ ORDER_ITEM : fulfils
    CATEGORY |o--o{ PRODUCT : groups
    ORDERS ||--o{ PAYMENT : "paid by"
    PAYMENT_TYPE ||--o{ PAYMENT : classifies
    ORDERS ||--o{ REVIEW : receives
    ORDERS ||--o{ ORDER_STATUS_LOG : "audited by"
    ORDERS ||--o| ML_PREDICTION : "scored by"
    ML_MODEL ||--o{ ML_PREDICTION : produces
    SELLER |o--o{ APP_USER : "logs in as"

    STATE {
        char2 state_code PK
        varchar state_name UK
        varchar region
    }
    ZIP_CODE {
        int zip_prefix PK
        varchar city
        char2 state_code FK
        numeric lat
        numeric lng
    }
    CUSTOMER {
        char32 customer_unique_id PK
    }
    CUSTOMER_ACCOUNT {
        char32 customer_id PK
        char32 customer_unique_id FK
        int zip_prefix FK
    }
    SELLER {
        char32 seller_id PK
        int zip_prefix FK
    }
    CATEGORY {
        varchar category_name PK
        varchar category_name_en UK
    }
    PRODUCT {
        char32 product_id PK
        varchar category_name FK
        int name_length
        int description_length
        int photos_qty
        int weight_g
        int length_cm
        int height_cm
        int width_cm
        int stock_qty
    }
    ORDERS {
        char32 order_id PK
        char32 customer_id FK
        varchar order_status
        timestamp purchase_ts
        timestamp approved_at
        timestamp delivered_carrier_date
        timestamp delivered_customer_date
        timestamp estimated_delivery_date
    }
    ORDER_ITEM {
        char32 order_id PK, FK
        int order_item_id PK
        char32 product_id FK
        char32 seller_id FK
        timestamp shipping_limit_date
        numeric price
        numeric freight_value
    }
    PAYMENT_TYPE {
        varchar payment_type PK
        varchar description
    }
    PAYMENT {
        char32 order_id PK, FK
        int payment_sequential PK
        varchar payment_type FK
        int installments
        numeric payment_value
    }
    REVIEW {
        char32 review_id PK
        char32 order_id PK, FK
        smallint review_score
        text comment_title
        text comment_message
        timestamp creation_date
        timestamp answer_ts
    }
    ORDER_STATUS_LOG {
        bigint log_id PK
        char32 order_id FK
        varchar old_status
        varchar new_status
        timestamp changed_at
        text changed_by
    }
    ML_MODEL {
        varchar model_version PK
        varchar algorithm
        numeric roc_auc
        numeric pr_auc
        numeric threshold
        boolean is_active
    }
    ML_PREDICTION {
        char32 order_id PK, FK
        varchar model_version FK
        numeric late_probability
        numeric predicted_days
        timestamp scored_at
    }
    APP_USER {
        int user_id PK
        varchar username UK
        text password_hash
        varchar app_role
        char32 seller_id FK
    }`;

// Functional dependencies and normal-form notes shown under the diagram.
window.NORMALIZATION = [
  ["order_id", "customer_id, order_status, purchase_ts, approved_at, delivered_*_date, estimated_delivery_date", "orders"],
  ["customer_id", "customer_unique_id, zip_prefix", "customer_account"],
  ["zip_prefix", "city, state_code", "zip_code"],
  ["state_code", "state_name, region", "state"],
  ["(order_id, order_item_id)", "product_id, seller_id, shipping_limit_date, price, freight_value", "order_item"],
  ["product_id", "category_name, name/description length, photos_qty, weight, dimensions, stock_qty", "product"],
  ["category_name  <->  category_name_en", "each determines the other (two candidate keys)", "category"],
  ["seller_id", "zip_prefix", "seller"],
  ["(order_id, payment_sequential)", "payment_type, installments, payment_value", "payment"],
  ["(review_id, order_id)", "review_score, comment_title, comment_message, creation_date, answer_ts", "review"],
];
