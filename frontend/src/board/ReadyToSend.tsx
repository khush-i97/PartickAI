/** A doorway, not the thing itself. Reviewing an email properly needs a page,
 *  so this says what is waiting and sends you there. */
import type { Board } from "../lib/board";

export function ReadyToSend({ board, caseId }: { board: Board; caseId: string | null }) {
  const offices = board.authorities.filter((a) => a.approval !== "removed");
  const sent = board.dispatches.filter((d) => d.status === "sent" || d.status === "delivered").length;
  if (offices.length === 0 || !caseId) return null;

  return (
    <section className="panel">
      <h2>Ready to send<span className="count">{offices.length}</span></h2>
      <p className="empty">
        {sent > 0
          ? `${sent} report${sent > 1 ? "s" : ""} sent. Read them, or send the rest, on the full page.`
          : "One email per office, with the transcript, summary and details attached as PDFs."}
      </p>
      <div className="actions">
        <a className="btn primary" href={`?send=${caseId}`}>Open the send page →</a>
      </div>
    </section>
  );
}
