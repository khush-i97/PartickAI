import { useRef, useState } from "react";
import { Call, type GatewayEvent } from "./audio/call";
import { AuthorityFinder, CaseFile, Dispatches, Inconsistencies, ToolLog, Transcript } from "./board/Panels";
import { Avatar, type AvatarHandle } from "./board/Avatar";
import { useBoard } from "./lib/board";

type Turn = { id: string; speaker: "patrick" | "caller"; text: string; final: boolean };
type Status = "idle" | "connecting" | "live" | "ended";

export default function App() {
  const [status, setStatus] = useState<Status>("idle");
  const [turns, setTurns] = useState<Turn[]>([]);
  // ?case=<id> opens a finished case read only, which is how eval calls are reviewed.
  const [caseId, setCaseId] = useState<string | null>(() => new URLSearchParams(location.search).get("case"));
  const board = useBoard(caseId);
  const [speaking, setSpeaking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const call = useRef<Call | null>(null);
  const meter = useRef<HTMLDivElement>(null);
  const avatar = useRef<AvatarHandle>(null);

  function onEvent(ev: GatewayEvent) {
    if (ev.type === "ready") setStatus("live");
    if (ev.type === "ended") {
      setStatus("ended");
      setError(ev.reason);
    }
    if (ev.type === "error") setError(JSON.stringify(ev.error));
    if (ev.type === "case") setCaseId(ev.case_id);
    if (ev.type === "transcript") {
      setTurns((prev) => {
        const i = prev.findIndex((t) => t.id === ev.item_id);
        // Patrick's words stream in as deltas; the final event carries the full text.
        if (i === -1) return [...prev, { id: ev.item_id, speaker: ev.speaker, text: ev.text, final: ev.final }];
        const next = [...prev];
        next[i] = { ...next[i], text: ev.final ? ev.text : next[i].text + ev.text, final: ev.final };
        return next;
      });
    }
  }

  async function toggle() {
    if (call.current) {
      await call.current.stop();
      call.current = null;
      setStatus("ended");
      return;
    }
    setError(null);
    setTurns([]);
    setStatus("connecting");
    const c = new Call({
      onEvent,
      onSpeaking: setSpeaking,
      onVoice: (rms) => avatar.current?.voice(rms),
      // Written straight to the DOM: 10 updates a second should not re-render React.
      onLevel: (rms) => meter.current?.style.setProperty("--level", String(Math.min(1, rms * 6))),
      onClose: () => setStatus((s) => (s === "idle" ? s : "ended")),
    });
    call.current = c;
    try {
      await c.start();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      await c.stop(); // do not leave a half-open call behind, e.g. when the mic is denied
      setStatus("idle");
      call.current = null;
    }
  }

  const live = status === "live" || status === "connecting";

  return (
    <div className="app">
      <header>
        <h1>Case Closed</h1>
        <p className="sub">Detective Patrick · voice intake</p>
      </header>

      <main>
        <section className="call">
          <Avatar
            ref={avatar}
            live={status === "live"}
            mood={board.inconsistencies.some((i) => i.status === "open" && i.kind !== "question") ? "serious" : "warm"}
          />
          <button
            className={`call-btn ${live ? "on" : ""}`}
            // Drop focus so a stray Space or Enter while talking cannot end the call.
            onClick={(e) => { e.currentTarget.blur(); toggle(); }}
            disabled={status === "connecting"}
          >
            {status === "connecting" ? "Connecting…" : live ? "End call" : "Call Patrick"}
          </button>
          <div className="meter" ref={meter} aria-hidden />
          <p className="state">
            {status === "idle" && "Tap to start. Speak any language. Calls are recorded for your case file."}
            {status === "connecting" && "Reaching the detective…"}
            {status === "live" && (speaking ? "Patrick is speaking" : "Patrick is listening")}
            {status === "ended" && "Call ended."}
          </p>
          {error && <p className="error">{error}</p>}
          <CaseFile board={board} />
          <Inconsistencies board={board} />
        </section>

        <div className="col">
          <Transcript live={turns} board={board} />
        </div>
        <div className="col">
          <AuthorityFinder board={board} />
          <Dispatches board={board} />
          <ToolLog board={board} />
        </div>
      </main>
    </div>
  );
}
