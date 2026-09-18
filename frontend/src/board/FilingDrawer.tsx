/** Where the call pays off: the offices Patrick found, how to reach them, the
 *  form filled with the caller's own answers, and what was actually sent.
 *
 *  It lives in a drawer rather than a rail because the brief wants Patrick to
 *  own the screen during the interview. None of this exists until he has
 *  searched, and when it does exist it deserves more width than a column. */
import { useState } from "react";
import type { Board, Row } from "../lib/board";
import { byTime, clock, summarize } from "./Panels";

export type DrawerTab = "filing" | "activity";

/** What the peek tab says when the drawer is shut: the top office and whether
 *  its form is ready, which is the thing worth interrupting someone for. */
export function drawerSummary(board: Board): string | null {
  const found = sortedAuthorities(board);
  if (found.length === 0) {
    const running = board.authority_searches.some((s) => s.status === "running");
    return running ? "Looking for the right office…" : null;
  }
  const top = found[0];
  const fields = board.form_fields.filter((f) => f.authority_id === top.id);
  const more = found.length > 1 ? ` + ${found.length - 1} more` : "";
  if (fields.length === 0) return `${top.name}${more}`;
  const answers = new Map(board.case_fields.map((f) => [f.field, f.value]));
  const filled = fields.filter((f) => f.maps_to && answers.has(f.maps_to)).length;
  return `${top.name}${more} · form ${filled}/${fields.length} filled`;
}

function sortedAuthorities(board: Board): Row[] {
  return [...board.authorities].sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99));
}

export function FilingDrawer({ board, open, onToggle }: { board: Board; open: boolean; onToggle: () => void }) {
  const [tab, setTab] = useState<DrawerTab>("filing");
  const summary = drawerSummary(board);
  // Nothing found and nothing searched: the drawer does not exist yet.
  if (!summary && board.tool_events.length === 0) return null;

  return (
    <div className={`drawer ${open ? "open" : ""}`}>
      <button className="drawer-tab" onClick={onToggle} aria-expanded={open}>
        <span className="caret">▲</span>
        <span>{summary ?? "Activity"}</span>
        <span className="muted">{open ? "· hide" : "· show details"}</span>
      </button>
      <div className="drawer-body">
        <div className="drawer-tabs">
          <button className={tab === "filing" ? "on" : ""} onClick={() => setTab("filing")}>Filing</button>
          <button className={tab === "activity" ? "on" : ""} onClick={() => setTab("activity")}>Activity</button>
        </div>
        {tab === "filing" ? <Filing board={board} /> : <Activity board={board} />}
      </div>
    </div>
  );
}

function Filing({ board }: { board: Board }) {
  const searches = [...board.authority_searches].sort(byTime);
  const found = sortedAuthorities(board);
  const dispatches = [...board.dispatches].sort(byTime);

  return (
    <>
      {searches.length > 0 && (
        <div className="searches">
          {searches.map((s) => (
            <p key={s.id} className={`search ${s.status}`}>
              <span className="dot" /> {s.query}
              {s.status === "failed" && <em> · failed</em>}
            </p>
          ))}
        </div>
      )}

      {found.length === 0 && (
        <p className="empty">Once the case type and the caller's city are known, Patrick searches for the right offices.</p>
      )}

      {found.length > 0 && (
        <div className="offices">
          {found.map((a, i) => <Office key={a.id} authority={a} rank={i + 1} board={board} />)}
        </div>
      )}

      <h4>Dispatch</h4>
      {dispatches.length === 0
        ? <p className="empty">Nothing is sent until the caller says yes.</p>
        : <Dispatches rows={dispatches} />}
    </>
  );
}

function Office({ authority, rank, board }: { authority: Row; rank: number; board: Board }) {
  return (
    <div className={`office ${authority.approval}`}>
      <span className="rank">
        {rank === 1 ? "First stop" : `Also #${rank}`}
        {authority.is_cached && <span className="badge" style={{ marginLeft: 6 }}>cached</span>}
        {authority.approval !== "pending" && <span className={`badge ${authority.approval}`} style={{ marginLeft: 6 }}>{authority.approval}</span>}
      </span>
      <h3>{authority.name}</h3>
      {authority.handles && <p className="handles">{authority.handles}</p>}
      {authority.reason && <p className="reason">{authority.reason}</p>}

      {/* The authorities table has no street address — these are the contact
          details Patrick actually found, laid out rather than crammed. */}
      <dl className="details">
        {authority.phone && <div><dt>Phone</dt><dd>{authority.phone}</dd></div>}
        {authority.email && <div><dt>Email</dt><dd>{authority.email}</dd></div>}
        {authority.form_url && (
          <div><dt>Form</dt><dd><a href={authority.form_url} target="_blank" rel="noreferrer">{authority.form_url} ↗</a></dd></div>
        )}
        {authority.source_url && (
          <div><dt>Source</dt><dd><a href={authority.source_url} target="_blank" rel="noreferrer">{authority.source_url} ↗</a></dd></div>
        )}
      </dl>

      <FormReady authority={authority} board={board} />
    </div>
  );
}

/** The real form's fields with the caller's answers. Values come live from the
 *  case file, so a field flips from "still needed" to filled as the caller answers. */
function FormReady({ authority, board }: { authority: Row; board: Board }) {
  const fields = board.form_fields.filter((f) => f.authority_id === authority.id).sort((a, b) => a.position - b.position);
  if (fields.length === 0) return null;
  const answers = new Map(board.case_fields.map((f) => [f.field, f.value]));
  const filled = fields.filter((f) => f.maps_to && answers.has(f.maps_to)).length;
  return (
    <details className="form-ready">
      <summary>
        Form ready · {filled}/{fields.length} filled
        <span className="badge" style={{ marginLeft: 6 }}>{fields[0].source === "form" ? "read from the live form" : "standard fields"}</span>
      </summary>
      <dl>
        {fields.map((f) => {
          const value = f.maps_to ? answers.get(f.maps_to) : undefined;
          return (
            <div key={f.id} className={value ? "filled" : "needed"}>
              <dt>{f.label}{f.required && " *"}</dt>
              <dd>{value ?? (f.maps_to ? "still needed" : "not collected by Patrick")}</dd>
            </div>
          );
        })}
      </dl>
      <p className="contact">
        Prepared only, never submitted.
        {authority.form_url && <a href={authority.form_url} target="_blank" rel="noreferrer">Open the real form ↗</a>}
      </p>
    </details>
  );
}

const STATUS_LABEL: Record<string, string> = {
  drafting: "Drafting…", sent: "Sent to demo inbox", delivered: "Delivered", blocked: "Blocked by safe mode", failed: "Failed",
};

function Dispatches({ rows }: { rows: Row[] }) {
  const [open, setOpen] = useState<Row | null>(null);
  return (
    <>
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
    </>
  );
}

/** Diagnostic, not something the caller needs — hence a drawer tab, not a rail. */
function Activity({ board }: { board: Board }) {
  const events = [...board.tool_events].sort(byTime).reverse();
  if (events.length === 0) return <p className="empty">Patrick's actions appear here as they fire.</p>;
  return (
    <div className="scroll">
      {events.map((e) => (
        <div key={e.id} className={`tool-line ${e.status}`}>
          <span className="at">{clock(e.created_at)}</span> <span className="name">{e.name}</span>
          {e.source === "backup" && <span className="badge" title="Filled in by the gateway's backup, not the voice model">backup</span>}{" "}
          <span className="args">{summarize(e.args)}</span>
        </div>
      ))}
    </div>
  );
}
