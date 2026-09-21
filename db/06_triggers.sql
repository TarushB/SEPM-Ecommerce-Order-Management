-- =====================================================================
-- 06_triggers.sql  --  business rules the CHECK constraints can't express.
-- Created AFTER the historical load so old data isn't re-validated.
-- =====================================================================
SET client_min_messages = warning;

-- ---------------------------------------------------------------------
-- 1. Status may only move forward:
--    created -> approved -> invoiced -> processing -> shipped -> delivered
--    canceled / unavailable are allowed from any state except delivered.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_status_rank(s TEXT) RETURNS INT
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE s WHEN 'created' THEN 1 WHEN 'approved' THEN 2 WHEN 'invoiced' THEN 3
                  WHEN 'processing' THEN 4 WHEN 'shipped' THEN 5 WHEN 'delivered' THEN 6
                  ELSE NULL END
$$;

CREATE OR REPLACE FUNCTION trg_validate_status_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.order_status = OLD.order_status THEN
        RETURN NEW;
    END IF;
    IF OLD.order_status IN ('delivered','canceled','unavailable') THEN
        RAISE EXCEPTION 'Order % is already % and cannot change to %',
              OLD.order_id, OLD.order_status, NEW.order_status
              USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.order_status IN ('canceled','unavailable') THEN
        RETURN NEW;
    END IF;
    IF fn_status_rank(NEW.order_status) <= fn_status_rank(OLD.order_status) THEN
        RAISE EXCEPTION 'Invalid status change for order %: % -> % (status can only move forward)',
              OLD.order_id, OLD.order_status, NEW.order_status
              USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_validate_status_transition ON orders;
CREATE TRIGGER trg_validate_status_transition
    BEFORE UPDATE OF order_status ON orders
    FOR EACH ROW EXECUTE FUNCTION trg_validate_status_transition();
