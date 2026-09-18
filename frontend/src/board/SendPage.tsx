/** The full page for reading what is about to go out.
 *
 *  A rail panel is the wrong place to check an email you are about to send to
 *  a police force: the body needs room, and the attachments need to be worth
 *  clicking. Where a send actually lands is still the gateway's decision — with
 *  safe mode on it goes to the demo inbox with the real office in the subject.
 */
import { useEffect, useState } from "react";

type Attachment = { name: string; url: string | null; bytes: number };
type Draft = {
  authority_id: string;
  to_name: string;
  to_address: string | null;
  address: string | null;
  phone?: string | null;
  form_url: string | null;
  source_url: string | null;
  subject: string;
  body_html: string;
  attachments: Attachment[];
  missing: string[];
  sendable: boolean;
};
type Packet = { case_id: string; summary: string; drafts: Draft[] };

const API = (import.meta.env.VITE_GATEWAY_URL || "").replace(/^ws/, "http");
const KB = (n: number) => `${Math.max(1, Math.round(n / 1024))} KB`;

export function SendPage({ caseId }: { caseId: string }) {
  const [packet, setPacket] = useState<Packet | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState(0);
  const [sending, setSending] = useState<Record<string, boolean>>({});
  const [sent, setSent] = useState<Record<string, string>>({});

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await fetch(`${API}/api/cases/${caseId}/packet`);
        if (!r.ok) throw new Error(String(r.status));
        const data = await r.json();
        if (alive) setPacket(data);
      } catch {
        if (alive) setError("Could not build the packet. Is the gateway running?");
      }
    })();
    return () => { alive = false; };
  }, [caseId]);

  async function send(d: Draft) {
    setSending((s) => ({ ...s, [d.authority_id]: true }));
    try {
      const r = await fetch(`${API}/api/cases/${caseId}/send/${d.authority_id}`, { method: "POST" });
      const out = await r.json();
      if (out.status !== "sent") throw new Error(out.error || "failed");
      setSent((s) => ({ ...s, [d.authority_id]: out.delivered_to }));
    } catch {
      setError(`Sending to ${d.to_name} failed. The gateway log has why.`);
    } finally {
      setSending((s) => ({ ...s, [d.authority_id]: false }));
    }
  }

  const draft = packet?.drafts[picked];

  return (
    <div className="send-page">
      <header className="topbar">
        <h1>Ready to send</h1>
        <p className="sub">case {caseId.slice(0, 8).toUpperCase()}</p>
        <span className="spacer" />
        <a className="ghost" href={`?case=${caseId}`}>← back to the case</a>
      </header>

      {error && <p className="error">{error}</p>}
      {!packet && !error && <p className="empty">Preparing the documents…</p>}

      {packet && (
        <div className="send-body">
          <nav className="send-list">
            {packet.drafts.map((d, i) => (
              <button
                key={d.authority_id}
                className={`send-item ${i === picked ? "on" : ""}`}
                onClick={() => setPicked(i)}
              >
                <strong>{d.to_name}</strong>
                <span className="status">
                  {sent[d.authority_id] ? "sent" : d.to_address ? d.to_address : "web form only"}
                </span>
              </button>
            ))}
            {packet.summary && (
              <p className="reason summary-note">{packet.summary}</p>
            )}
          </nav>

          {draft && (
            <article className="send-detail">
              <dl className="details">
                <div><dt>To</dt><dd>{draft.to_address ?? `${draft.to_name} — no email published`}</dd></div>
                {draft.address && <div><dt>Address</dt><dd>{draft.address}</dd></div>}
                <div><dt>Subject</dt><dd>{draft.subject}</dd></div>
              </dl>

              <h2>The email</h2>
              {/* Our own generated HTML, sandboxed so nothing in it can run. */}
              <iframe className="mail" title={`Email to ${draft.to_name}`} sandbox="" srcDoc={draft.body_html} />

              <h2>Attached</h2>
              <ul className="files">
                {draft.attachments.map((a) => (
                  <li key={a.name}>
                    <span className="kind">{a.name.endsWith(".pdf") ? "PDF" : "TXT"}</span>
                    {a.url
                      ? <a href={a.url} target="_blank" rel="noreferrer">{a.name}</a>
                      : <span>{a.name}</span>}
                    <span className="status">{KB(a.bytes)}</span>
                  </li>
                ))}
              </ul>

              {draft.missing.length > 0 && (
                <p className="reason">Their form still wants: {draft.missing.join(", ")}</p>
              )}

              <div className="actions">
                <button
                  className="btn primary big"
                  onClick={() => send(draft)}
                  disabled={sending[draft.authority_id] || !!sent[draft.authority_id]}
                >
                  {sending[draft.authority_id] ? "Sending…"
                    : sent[draft.authority_id] ? "Sent" : "Send this report"}
                </button>
                {draft.form_url && (
                  <a className="btn" href={draft.form_url} target="_blank" rel="noreferrer">Open their form ↗</a>
                )}
                {draft.source_url && (
                  <a className="btn" href={draft.source_url} target="_blank" rel="noreferrer">Where this came from ↗</a>
                )}
              </div>

              {sent[draft.authority_id] ? (
                <p className="reason">
                  Delivered to <strong>{sent[draft.authority_id]}</strong> with {draft.attachments.length} files.
                  Safe mode is on, so {draft.to_name} was named in the subject but not mailed.
                </p>
              ) : (
                <p className="reason">
                  Safe mode is on: this goes to the demo inbox, with {draft.to_name} named in the subject.
                  Nothing reaches a real police force or agency.
                </p>
              )}
            </article>
          )}
        </div>
      )}
    </div>
  );
}
