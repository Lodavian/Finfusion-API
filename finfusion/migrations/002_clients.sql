SET search_path TO finfusion;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS can_read BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS can_trade BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS can_cancel BOOLEAN NOT NULL DEFAULT FALSE;
CREATE TABLE IF NOT EXISTS request_nonces (
    client_id UUID NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    nonce TEXT NOT NULL,
    seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (client_id, nonce)
);
CREATE INDEX IF NOT EXISTS nonce_time_idx ON request_nonces(seen_at);
CREATE TABLE IF NOT EXISTS deployment_environment (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    environment TEXT NOT NULL CHECK (environment IN ('SANDBOX', 'LIVE'))
);
