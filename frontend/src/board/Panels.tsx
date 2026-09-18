import { useEffect, useRef, useState } from "react";
import type { Board, Row } from "../lib/board";

export type LiveTurn = { id: string; speaker: "rook" | "caller"; text: string };

const FIELD_LABELS: Record<string, string> = {
  caller_name: "Caller", caller_email: "Caller email", what_happened: "What happened", when: "When",
  who_involved: "Who was involved", amount: "Amount", reference_numbers: "Reference numbers",
  evidence: "Evidence", desired_outcome: "Wants", location: "Location", address: "Address",
  bank_name: "Bank", account_last4: "Account ending", company_name: "Company", property_manager: "Property manager",
};

const byTime = (a: Row, b: Row) => (a.created_at ?? "").localeCompare(b.created_at ?? "");
const clock = (iso?: string) => (iso ? new Date(iso).toLocaleTimeString([], { hour12: false }) : "");

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
                {t.speaker === "rook" ? "Rook" : "Caller"}
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

export function CaseFile({ board }: { board: Board }) {
  const c = board.cases[0];
  return (
    <Panel title="Case file" count={board.case_fields.length}>
      {c?.case_type && (
        <p className="case-type">
          {String(c.case_type).replace(/_/g, " ")}
          {c.confidence != null && <span> · {Math.round(c.confidence * 100)}% sure</span>}
        </p>
      )}
      {board.case_fields.length === 0 && <p className="empty">Facts fill in here as Rook hears them.</p>}
      <dl className="fields">
        {[...board.case_fields].sort((a, b) => a.updated_at.localeCompare(b.updated_at)).map((f) => (
          // Keyed on the value too, so a corrected fact replays its highlight.
          <div key={f.id + f.value} className="field fresh">
            <dt>{FIELD_LABELS[f.field] ?? f.field}</dt>
            <dd>{f.value}</dd>
          </div>
        ))}
      </dl>
    </Panel>
  );
}

export function Inconsistencies({ board }: { board: Board }) {
  const open = board.inconsistencies.filter((i) => i.status === "open");
  return (
    <Panel title="Inconsistencies" count={board.inconsistencies.length} alert={open.length > 0}>
      {board.inconsistencies.length === 0 && <p className="empty">Nothing conflicts so far.</p>}
      {board.inconsistencies.map((i) => (
        <p key={i.id} className="conflict">{i.description}</p>
      ))}
    </Panel>
  );
}

export function ToolLog({ board }: { board: Board }) {
  const events = [...board.tool_events].sort(byTime).reverse();
  return (
    <Panel title="Tool calls" count={events.length} className="log">
      <div className="scroll short">
        {events.length === 0 && <p className="empty">Rook's actions appear here as they fire.</p>}
        {events.map((e) => (
          <div key={e.id} className={`tool-line ${e.status}`}>
            <span className="at">{clock(e.created_at)}</span> <span className="name">{e.name}</span>
            {e.source === "backup" && <span className="badge" title="Filled in by the gateway's backup, not the voice model">backup</span>}{" "}
            <span className="args">{summarize(e.args)}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function summarize(args: Record<string, unknown> | null): string {
  if (!args) return "";
  return Object.values(args).map((v) => (typeof v === "string" ? v : JSON.stringify(v))).join(" · ");
}

export function AuthorityFinder({ board }: { board: Board }) {
  const searches = [...board.authority_searches].sort(byTime);
  const found = [...board.authorities].sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99));
  return (
    <Panel title="Authority finder" count={found.length}>
      {searches.length === 0 && found.length === 0 && (
        <p className="empty">Once the case type and location are known, Rook searches for the right offices here.</p>
      )}
      {searches.map((s) => (
        <p key={s.id} className={`search ${s.status}`}>
          <span className="dot" /> {s.query}
          {s.status === "failed" && <em> · failed</em>}
        </p>
      ))}
      {found.map((a) => (
        <div key={a.id} className={`authority ${a.approval}`}>
          <div className="row">
            <strong>{a.name}</strong>
            {a.is_cached && <span className="badge">cached result</span>}
            {a.approval !== "pending" && <span className={`badge ${a.approval}`}>{a.approval}</span>}
          </div>
          {a.reason && <p className="reason">{a.reason}</p>}
          <p className="contact">
            {a.email && <span>{a.email}</span>}
            {a.phone && <span>{a.phone}</span>}
            {a.form_url && <a href={a.form_url} target="_blank" rel="noreferrer">web form ↗</a>}
            {a.source_url && <a href={a.source_url} target="_blank" rel="noreferrer">source ↗</a>}
          </p>
        </div>
      ))}
    </Panel>
  );
}

const STATUS_LABEL: Record<string, string> = {
  drafting: "Drafting…", sent: "Sent to demo inbox", delivered: "Delivered", blocked: "Blocked by safe mode", failed: "Failed",
};

export function Dispatches({ board }: { board: Board }) {
  const [open, setOpen] = useState<Row | null>(null);
  const rows = [...board.dispatches].sort(byTime);
  return (
    <Panel title="Dispatch" count={rows.length}>
      {rows.length === 0 && <p className="empty">Nothing is sent until the caller says yes.</p>}
      {rows.map((d) => (
        <div key={d.id} className={`dispatch ${d.status}`}>
          <div className="row">
            <strong>{d.intended_name ?? (d.kind === "caller" ? "Caller confirmation" : "Report")}</strong>
            <span className={`status ${d.status}`}>{STATUS_LABEL[d.status] ?? d.status}</span>
          </div>
          <p className="contact">
            <span>Intended for: {d.intended_recipient ?? d.form_url ?? "unknown"}</span>
            {d.delivered_to && <span className="badge">Redirected to demo inbox</span>}
          </p>
          {d.body_html && <button className="link" onClick={() => setOpen(d)}>View the exact email</button>}
        </div>
      ))}
      {open && (
        <div className="modal" onClick={() => setOpen(null)}>
          <div className="sheet" onClick={(e) => e.stopPropagation()}>
            <p className="subject">{open.subject}</p>
            <p className="contact">Delivered to: {open.delivered_to}</p>
            {/* The email body is our own generated HTML; sandboxed so nothing in it can run. */}
            <iframe title="email" sandbox="" srcDoc={open.body_html} />
            <button className="link" onClick={() => setOpen(null)}>Close</button>
          </div>
        </div>
      )}
    </Panel>
  );
}
