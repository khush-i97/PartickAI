/** The rails either side of Patrick: what was said, and what he pulled out of
 *  it. Everything about filing lives in FilingDrawer. */
import { useEffect, useRef } from "react";
import type { Board, Row } from "../lib/board";

export type LiveTurn = { id: string; speaker: "patrick" | "caller"; text: string };

const FIELD_LABELS: Record<string, string> = {
  caller_name: "Caller", caller_email: "Caller email", what_happened: "What happened", when: "When",
  who_involved: "Who was involved", amount: "Amount", reference_numbers: "Reference numbers",
  evidence: "Evidence", desired_outcome: "Wants", location: "Location", address: "Address",
  phone: "Phone", date_of_birth: "Date of birth", item_description: "Item", place_lost: "Lost at",
  bank_name: "Bank", account_last4: "Account ending", company_name: "Company", property_manager: "Property manager",
};

export const byTime = (a: Row, b: Row) => (a.created_at ?? "").localeCompare(b.created_at ?? "");
export const clock = (iso?: string) => (iso ? new Date(iso).toLocaleTimeString([], { hour12: false }) : "");

export function summarize(args: Record<string, unknown> | null): string {
  if (!args) return "";
  return Object.values(args).map((v) => (typeof v === "string" ? v : JSON.stringify(v))).join(" · ");
}

function Panel(props: { title: string; count?: number; alert?: boolean; className?: string; children: React.ReactNode }) {
  return (
    <section className={`panel ${props.className ?? ""} ${props.alert ? "alert" : ""}`}>
      <h2>
        {props.title}
        {props.count ? <span className="count">{props.count}</span> : null}
      </h2>
      {props.children}
    </section>
  );
}

/** Live words arrive over the call socket; the English line arrives from the database. */
export function Transcript({ live, board }: { live: LiveTurn[]; board: Board }) {
  const end = useRef<HTMLDivElement>(null);
  const stored = new Map(board.transcript_turns.map((t) => [t.item_id, t]));
  // When viewing a finished case there are no live turns, only stored ones.
  const turns: LiveTurn[] = live.length
    ? live
    : [...board.transcript_turns].sort(byTime).map((t) => ({ id: t.item_id, speaker: t.speaker, text: t.original_text }));
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [turns.length, turns.at(-1)?.text]);

  return (
    <Panel title="Transcript" className="transcript">
      <div className="scroll">
        {turns.length === 0 && <p className="empty">The conversation will appear here, in the caller's language and in English.</p>}
        {turns.map((t) => {
          const row = stored.get(t.id);
          const english = row?.english_text && row.english_text.trim() !== t.text.trim() ? row.english_text : null;
          return (
            <div key={t.id} className={`turn ${t.speaker}`}>
              <span className="who">
                {t.speaker === "patrick" ? "Patrick" : "Caller"}
                {row?.language && <em> · {row.language}</em>}
              </span>
              <p>{t.text}</p>
              {english && <p className="english">{english}</p>}
            </div>
          );
        })}
        <div ref={end} />
      </div>
    </Panel>
  );
}

/* The report reads top to bottom the way a complaint does: who is calling,
   what happened, then the specifics. Anything Patrick heard that is not in this
   order still appears, at the end, rather than being dropped. */
const REPORT_ORDER = [
  "caller_name", "phone", "caller_email", "date_of_birth",
  "what_happened", "when", "location", "address", "place_lost",
  "item_description", "amount", "bank_name", "account_last4", "company_name", "property_manager",
  "who_involved", "reference_numbers", "evidence", "desired_outcome",
];

export function Report({ board }: { board: Board }) {
  const c = board.cases[0];
  const byField = new Map(board.case_fields.map((f) => [f.field, f]));
  const known = REPORT_ORDER.filter((k) => byField.has(k));
  const extra = [...byField.keys()].filter((k) => !REPORT_ORDER.includes(k));
  const rows = [...known, ...extra].map((k) => byField.get(k)!);

  return (
    <Panel title="Report" count={rows.length}>
      {c?.case_type && (
        <p className="case-type">
          {String(c.case_type).replace(/_/g, " ")}
          {c.confidence != null && <span> · {Math.round(c.confidence * 100)}% sure</span>}
        </p>
      )}
      {rows.length === 0 && <p className="empty">The report writes itself as Patrick hears the details.</p>}
      <dl className="fields">
        {rows.map((f) => (
          // Keyed on the value too, so a corrected fact replays its highlight.
          <div key={f.id + f.value} className="field fresh">
            <dt>{FIELD_LABELS[f.field] ?? f.field.replace(/_/g, " ")}</dt>
            <dd>{f.value}</dd>
          </div>
        ))}
      </dl>
    </Panel>
  );
}

/** Where this actually goes, with the numbers and addresses to use. The whole
 *  point of the call, so it sits in the rail rather than behind a click. */
export function WhereToFile({ board }: { board: Board }) {
  const found = [...board.authorities]
    .filter((a) => a.approval !== "removed")
    .sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99));
  const searching = board.authority_searches.some((s) => s.status === "running");

  return (
    <Panel title="Where to file" count={found.length}>
      {found.length === 0 && (
        <p className="empty">
          {searching ? "Looking for the offices that handle this…"
                     : "Once Patrick knows the case type and the caller's city, the right offices appear here."}
        </p>
      )}
      {found.map((a) => (
        <div key={a.id} className="office-brief">
          <h3>{a.name}</h3>
          {a.handles && <p className="handles">{a.handles}</p>}
          <dl className="details">
            {a.phone && <div><dt>Phone</dt><dd>{a.phone}</dd></div>}
            {a.email && <div><dt>Email</dt><dd>{a.email}</dd></div>}
            {a.form_url && (
              <div><dt>File at</dt><dd><a href={a.form_url} target="_blank" rel="noreferrer">{a.form_url} ↗</a></dd></div>
            )}
            {a.source_url && (
              <div><dt>Source</dt><dd><a href={a.source_url} target="_blank" rel="noreferrer">{a.source_url} ↗</a></dd></div>
            )}
          </dl>
        </div>
      ))}
    </Panel>
  );
}

export function Inconsistencies({ board }: { board: Board }) {
  const conflicts = board.inconsistencies.filter((i) => i.kind !== "question");
  const questions = board.inconsistencies.filter((i) => i.kind === "question");
  const open = conflicts.filter((i) => i.status === "open");
  return (
    <Panel title="Live analysis" count={board.inconsistencies.length} alert={open.length > 0}>
      {board.inconsistencies.length === 0 && <p className="empty">Every statement is checked against the rest. Nothing conflicts so far.</p>}
      {conflicts.map((i) => (
        <p key={i.id} className={`conflict ${i.status}`}>
          <span className="tag">{i.status === "open" ? "Conflict" : "Settled"}</span> {i.description}
        </p>
      ))}
      {questions.map((i) => (
        <p key={i.id} className="conflict question">
          <span className="tag">Worth probing</span> {i.description}
        </p>
      ))}
    </Panel>
  );
}
