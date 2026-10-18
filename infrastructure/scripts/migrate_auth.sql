ALTER TABLE organizations ADD COLUMN IF NOT EXISTS display_name VARCHAR(128);

CREATE TABLE IF NOT EXISTS dashboard_accounts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  login VARCHAR(64) UNIQUE NOT NULL,
  password_hash VARCHAR(256) NOT NULL,
  role VARCHAR(32) NOT NULL,
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  user_id UUID REFERENCES app_users(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dashboard_accounts_login ON dashboard_accounts(login);
