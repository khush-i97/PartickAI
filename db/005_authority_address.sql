-- The office's postal address, when the search results actually show one.
-- Nullable on purpose: plenty of agencies publish a phone and an online form
-- and no walk-in address, and an invented address on a filed report is worse
-- than none. Additive, so older rows simply carry null.
ALTER TABLE authorities ADD COLUMN IF NOT EXISTS address text;
