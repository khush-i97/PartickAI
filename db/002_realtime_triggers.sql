-- Every case board change is pushed to the browser. No polling.
-- InsForge does not broadcast table changes by itself, so one generic trigger
-- publishes each row on the channel case:<case id>.

INSERT INTO realtime.channels (pattern, description, enabled)
VALUES ('case:%', 'Live case board updates for one call', true),
       ('evals', 'Evaluation run updates', true)
ON CONFLICT (pattern) DO UPDATE SET enabled = EXCLUDED.enabled;

CREATE OR REPLACE FUNCTION public.publish_case_change()
RETURNS TRIGGER AS $$
DECLARE
  cid text;
BEGIN
  IF TG_TABLE_NAME = 'cases' THEN
    cid := NEW.id::text;
  ELSE
    cid := NEW.case_id::text;
  END IF;
  -- body_html can be large; the board fetches it when "view email" is clicked.
  PERFORM realtime.publish('case:' || cid, 'change',
    jsonb_build_object('table', TG_TABLE_NAME, 'row', to_jsonb(NEW) - 'body_html'));
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE FUNCTION public.publish_eval_change()
RETURNS TRIGGER AS $$
BEGIN
  PERFORM realtime.publish('evals', 'change',
    jsonb_build_object('table', TG_TABLE_NAME, 'row', to_jsonb(NEW)));
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['cases','case_fields','transcript_turns','inconsistencies',
                           'tool_events','authority_searches','authorities','dispatches'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON public.%I', t || '_publish', t);
    EXECUTE format('CREATE TRIGGER %I AFTER INSERT OR UPDATE ON public.%I
                    FOR EACH ROW EXECUTE FUNCTION public.publish_case_change()', t || '_publish', t);
  END LOOP;
  FOREACH t IN ARRAY ARRAY['eval_runs','eval_results'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON public.%I', t || '_publish', t);
    EXECUTE format('CREATE TRIGGER %I AFTER INSERT OR UPDATE ON public.%I
                    FOR EACH ROW EXECUTE FUNCTION public.publish_eval_change()', t || '_publish', t);
  END LOOP;
END $$;
