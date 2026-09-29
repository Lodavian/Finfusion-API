SET search_path TO finfusion;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS pending_action TEXT NOT NULL DEFAULT '';
ALTER TABLE orders ADD COLUMN IF NOT EXISTS previous_limit_price TEXT;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS previous_notional TEXT;
