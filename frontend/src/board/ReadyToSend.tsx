/** The packet, for a person to read before it goes.
 *
 *  Send is real, but where it lands is the gateway's decision, not this
 *  component's: with safe mode on it goes to the demo inbox with the real
 *  office named in the subject. Nothing here can address a police force
 *  directly, however the button is wired. */
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
  const [sending, setSending] = useState<Record<string, "sending" | "failed">>({});
  const [sent, setSent] = useState<Record<string, string>>({});

  async function send(d: Draft) {
    setSending((s) => ({ ...s, [d.authority_id]: "sending" }));
    try {
      const r = await fetch(`${API}/api/cases/${caseId}/send/${d.authority_id}`, { method: "POST" });
      const out = await r.json();
      if (out.status !== "sent") throw new Error(out.error || "failed");
      setSent((s) => ({ ...s, [d.authority_id]: out.delivered_to }));
      setSending((s) => ({ ...s, [d.authority_id]: undefined as never }));
    } catch {
      setSending((s) => ({ ...s, [d.authority_id]: "failed" }));
    }
  }
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
            <button
              className="btn primary"
              onClick={() => send(d)}
              disabled={sending[d.authority_id] === "sending" || sent[d.authority_id] !== undefined}
            >
              {sending[d.authority_id] === "sending" ? "Sending…"
                : sent[d.authority_id] ? "Sent" : "Send with the files"}
            </button>
            {d.form_url && (
              <a className="btn" href={d.form_url} target="_blank" rel="noreferrer">Open their form ↗</a>
            )}
          </div>
          {sent[d.authority_id] && (
            <p className="reason">
              Delivered to <strong>{sent[d.authority_id]}</strong>, with {d.attachments.length} files attached.
              Safe mode is on, so {d.to_name} was named in the subject but not mailed.
            </p>
          )}
          {sending[d.authority_id] === "failed" && <p className="error">That send failed. The gateway log has why.</p>}
          {!d.sendable && !sent[d.authority_id] && (
            <p className="reason">
              This office takes reports through its web form, not email. Open the form and paste from answers.txt.
            </p>
          )}
        </div>
      ))}

      {packet && (
        <p className="reason">
          Safe mode is on: every send goes to the demo inbox with the real office named in the subject.
          Nothing reaches an actual police force or agency.
        </p>
      )}
    </section>
  );
}
