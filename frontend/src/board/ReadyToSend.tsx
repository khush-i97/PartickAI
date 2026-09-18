/** The packet, ready for a person to look at before anything leaves.
 *
 *  Sending is off. There is no send endpoint on the gateway either, so this
 *  cannot be turned on from the browser alone — reporting to a real police
 *  force should take a deliberate decision, not a stray click. */
import { useEffect, useState } from "react";
import type { Board } from "../lib/board";

type Attachment = { name: string; url: string | null };
type Draft = {
  authority_id: string;
  to_name: string;
  to_address: string | null;
  form_url: string | null;
  subject: string;
  body_html: string;
  attachments: Attachment[];
  missing: string[];
  sendable: boolean;
};
type Packet = { summary: string; drafts: Draft[] };

// The gateway is the same host, over http rather than the call's websocket.
const API = (import.meta.env.VITE_GATEWAY_URL || "").replace(/^ws/, "http");

export function ReadyToSend({ board, caseId }: { board: Board; caseId: string | null }) {
  const [packet, setPacket] = useState<Packet | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "failed">("idle");
  const ready = board.authorities.filter((a) => a.approval !== "removed").length;

  async function build() {
    if (!caseId) return;
    setState("loading");
    try {
      const r = await fetch(`${API}/api/cases/${caseId}/packet`);
      if (!r.ok) throw new Error(String(r.status));
      setPacket(await r.json());
      setState("idle");
    } catch {
      setState("failed");
    }
  }

  // Rebuild when an office arrives, so the packet matches what is on screen.
  useEffect(() => { setPacket(null); }, [caseId]);

  if (ready === 0) return null;

  return (
    <section className="panel">
      <h2>Ready to send{packet ? <span className="count">{packet.drafts.length}</span> : null}</h2>

      {!packet && (
        <>
          <p className="empty">
            One email per office, with the transcript, summary and full details as PDFs, and a plain-text copy
            for their online form.
          </p>
          <div className="actions">
            <button className="btn primary" onClick={build} disabled={state === "loading"}>
              {state === "loading" ? "Preparing…" : "Prepare the packet"}
            </button>
          </div>
          {state === "failed" && <p className="error">Could not reach the gateway to build the packet.</p>}
        </>
      )}

      {packet?.drafts.map((d) => (
        <div key={d.authority_id} className="draft">
          <div className="row">
            <h3>{d.to_name}</h3>
            <span className="status">{d.to_address ?? "no email — web form only"}</span>
          </div>
          <p className="subject-line">{d.subject}</p>
          {/* Our own generated HTML, sandboxed so nothing in it can run. */}
          <iframe className="preview" title={`Email to ${d.to_name}`} sandbox="" srcDoc={d.body_html} />

          <p className="contact">
            {d.attachments.map((a) => (
              a.url
                ? <a key={a.name} href={a.url} target="_blank" rel="noreferrer">{a.name} ↗</a>
                : <span key={a.name}>{a.name} (failed)</span>
            ))}
          </p>

          {d.missing.length > 0 && (
            <p className="reason">Still missing: {d.missing.join(", ")}</p>
          )}

          <div className="actions">
            <button className="btn" disabled title="Sending is switched off">Send</button>
            {d.form_url && (
              <a className="btn primary" href={d.form_url} target="_blank" rel="noreferrer">Open their form ↗</a>
            )}
          </div>
          {!d.sendable && (
            <p className="reason">
              This office takes reports through its web form, not email. Open the form and paste from answers.txt.
            </p>
          )}
        </div>
      ))}

      {packet && (
        <p className="reason">
          Nothing has been sent. Sending is switched off, and the gateway has no send route yet.
        </p>
      )}
    </section>
  );
}
