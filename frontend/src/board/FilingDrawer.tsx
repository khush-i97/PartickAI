/** What was actually sent, and Patrick's working notes.
 *
 *  The offices and their forms live in the right rail, where the caller can act
 *  on them. This keeps the things they only need after the fact: the dispatched
 *  reports with the exact email, the analyst's open questions, and the tool log. */
import { useState } from "react";
import type { Board, Row } from "../lib/board";
import { byTime, clock, summarize } from "./Panels";

export type DrawerTab = "filing" | "activity";

/** What the peek tab says when the drawer is shut. The offices and the form are
 *  on the rail now, so this reports on sending, which is the only part that
 *  happens out of sight. */
export function drawerSummary(board: Board): string | null {
  const sent = board.dispatches.filter((d) => d.status === "sent" || d.status === "delivered").length;
  if (board.dispatches.length > 0) {
    const label = sent === board.dispatches.length ? "sent" : `${sent} of ${board.dispatches.length} sent`;
    return `Reports ${label} · see the exact emails`;
  }
  if (board.authority_searches.some((s) => s.status === "running")) return "Looking for the right office…";
  return null;
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
          <button className={tab === "filing" ? "on" : ""} onClick={() => setTab("filing")}>Dispatch</button>
          <button className={tab === "activity" ? "on" : ""} onClick={() => setTab("activity")}>Activity</button>
        </div>
        {tab === "filing" ? <Filing board={board} /> : <Activity board={board} />}
      </div>
    </div>
  );
}

function Filing({ board }: { board: Board }) {
  const dispatches = [...board.dispatches].sort(byTime);
  return dispatches.length === 0
    ? <p className="empty">Nothing is sent until the caller says yes. What was sent, and the exact email, appears here.</p>
    : <Dispatches rows={dispatches} />;
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

/** Diagnostic, not something the caller needs — hence a drawer tab, not a rail.
 *  The analyst's open questions live here too: they are Patrick's working notes,
 *  and on the rail they read as the report contradicting itself. */
function Activity({ board }: { board: Board }) {
  const events = [...board.tool_events].sort(byTime).reverse();
  const conflicts = board.inconsistencies.filter((i) => i.kind !== "question" && i.status === "open");
  const questions = board.inconsistencies.filter((i) => i.kind === "question");
  return (
    <>
      {(conflicts.length > 0 || questions.length > 0) && (
        <>
          <h4>Live analysis</h4>
          {conflicts.map((i) => (
            <p key={i.id} className="conflict open">
              <span className="tag">Conflict</span> {i.description}
            </p>
          ))}
          {questions.map((i) => (
            <p key={i.id} className="conflict question">
              <span className="tag">Worth probing</span> {i.description}
            </p>
          ))}
        </>
      )}
      <h4>Tool calls</h4>
      {events.length === 0 && <p className="empty">Patrick's actions appear here as they fire.</p>}
      {events.map((e) => (
        <div key={e.id} className={`tool-line ${e.status}`}>
          <span className="at">{clock(e.created_at)}</span> <span className="name">{e.name}</span>
          {e.source === "backup" && <span className="badge" title="Filled in by the gateway's backup, not the voice model">backup</span>}{" "}
          <span className="args">{summarize(e.args)}</span>
        </div>
      ))}
    </>
  );
}
