-- Mock bank data for the scam demo. All of it is invented.
-- Planted mismatch: the caller will say the money left on Tuesday, but the
-- transfer posted on Monday of the current week. Dates are relative so the
-- demo stays fresh whenever it is seeded.

DELETE FROM mock_accounts;

WITH acct AS (
  INSERT INTO mock_accounts (holder_name, bank_name, account_hint) VALUES
    ('Priya Sharma', 'HDFC Bank', '4821'),
    ('Daniel Reyes', 'Chase Bank', '7730')
  RETURNING id, account_hint
), monday AS (
  SELECT date_trunc('week', now()) AS d
)
INSERT INTO mock_transactions (account_id, posted_at, amount, currency, direction, counterparty, reference, description)
SELECT a.id, m.d + t.offs, t.amount, t.currency, t.direction, t.counterparty, t.reference, t.description
FROM acct a, monday m, (VALUES
  ('4821', interval '-3 days 10 hours',   1250.00, 'INR', 'debit',  'BigBasket',          'UPI/426598110233', 'Groceries'),
  ('4821', interval '-2 days 18 hours',  62000.00, 'INR', 'credit', 'Acme Infotech Pvt',  'NEFT/N257260011',  'Salary'),
  ('4821', interval '14 hours 29 minutes',   1.00, 'INR', 'debit',  'RK Enterprises',     'UPI/426712345601', 'UPI test payment'),
  ('4821', interval '14 hours 32 minutes', 45000.00, 'INR', 'debit', 'RK Enterprises',    'UPI/426712345678', 'UPI transfer authorised by OTP'),
  ('4821', interval '1 day 9 hours',       349.00, 'INR', 'debit',  'Netflix',            'CARD/88213',       'Subscription'),
  ('7730', interval '-1 days 12 hours',     84.20, 'USD', 'debit',  'Safeway',            'POS/119283',       'Groceries'),
  ('7730', interval '2 days 11 hours',     950.00, 'USD', 'debit',  'Zelle to J. Carter', 'ZEL/55102938',     'Zelle transfer')
) AS t(hint, offs, amount, currency, direction, counterparty, reference, description)
WHERE a.account_hint = t.hint;
