-- "Form ready": the fields a real complaint form asks for, mapped onto the case file.
-- Nothing is ever submitted; this is what a person would copy into the real form.
CREATE TABLE IF NOT EXISTS form_fields (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id      uuid NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  authority_id uuid NOT NULL REFERENCES authorities(id) ON DELETE CASCADE,
  position     int NOT NULL,
  label        text NOT NULL,              -- the field's label on the real form
  required     boolean NOT NULL DEFAULT false,
  maps_to      text,                       -- case file key that answers it, if any
  source       text NOT NULL DEFAULT 'form', -- form (read from the live page) | standard (routing.yaml)
  created_at   timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT ON form_fields TO anon;
DROP TRIGGER IF EXISTS form_fields_publish ON public.form_fields;
CREATE TRIGGER form_fields_publish AFTER INSERT OR UPDATE ON public.form_fields
  FOR EACH ROW EXECUTE FUNCTION public.publish_case_change();
