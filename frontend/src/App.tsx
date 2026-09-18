import { useEffect, useRef, useState } from "react";
import { Call, type GatewayEvent } from "./audio/call";
import { FormToFill, Report, Transcript, WhereToFile } from "./board/Panels";
import { ReadyToSend } from "./board/ReadyToSend";
import { FilingDrawer, drawerSummary } from "./board/FilingDrawer";
import { Avatar, type AvatarHandle } from "./board/Avatar";
import { useBoard } from "./lib/board";

type Turn = { id: string; speaker: "patrick" | "caller"; text: string; final: boolean };
type Status = "idle" | "connecting" | "live" | "ended";

export default function App() {
  const [status, setStatus] = useState<Status>("idle");
  const [turns, setTurns] = useState<Turn[]>([]);
  // ?case=<id> opens a finished case read only, which is how eval calls are reviewed.
  const [caseId, setCaseId] = useState<string | null>(() => new URLSearchParams(location.search).get("case"));
  const reviewing = useRef(Boolean(new URLSearchParams(location.search).get("case"))).current;
  const board = useBoard(caseId);
  const [speaking, setSpeaking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // A review opens with everything already found, so the drawer starts open.
  const [drawerOpen, setDrawerOpen] = useState(reviewing);
  const autoOpened = useRef(reviewing);
  const [demo, setDemo] = useState<"idle" | "running" | "failed">("idle");
  const call = useRef<Call | null>(null);
  const meter = useRef<HTMLDivElement>(null);
  const avatar = useRef<AvatarHandle>(null);

  // Open the drawer once, the first time something is actually sent. After that
  // it is the caller's to open and close: it must not fight them. (Offices and
  // the form are on the rail, so there is nothing to announce before this.)
  const hasSent = board.dispatches.length > 0;
  useEffect(() => {
    if (hasSent && !autoOpened.current) {
      autoOpened.current = true;
      setDrawerOpen(true);
    }
  }, [hasSent]);

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

  // Fills a case the way a call would, for showing the app without a mic. The
  // offices and forms in it are found live, not faked.
  async function runDemo() {
    setDemo("running");
    try {
      const api = (import.meta.env.VITE_GATEWAY_URL || "").replace(/^ws/, "http");
      const r = await fetch(`${api}/api/demo`, { method: "POST" });
      const out = await r.json();
      if (!out.case_id) throw new Error("no case");
      location.search = `?case=${out.case_id}`;
    } catch {
      setDemo("failed");
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
  const hasDrawer = drawerSummary(board) !== null || board.tool_events.length > 0;
  // Keep the rails clear of the drawer's tab, and of the drawer itself when open.
  const drawerSpace = !hasDrawer ? "16px" : drawerOpen ? "min(44vh, 425px)" : "60px";

  return (
    <div className={`call-screen ${drawerOpen && hasDrawer ? "drawer-open" : ""}`} style={{ ["--drawer-space" as string]: drawerSpace }}>
      <header className="topbar">
        <h1>Patrick</h1>
        <p className="sub">Voice detective · tell him what happened</p>
        <span className="spacer" />
        {reviewing && <span className="reviewing">Reviewing a finished case</span>}
        {/* Tucked into the corner: useful for showing the app, never the point of it. */}
        {status === "idle" && !reviewing && (
          <button className="ghost" onClick={runDemo} disabled={demo === "running"}>
            {demo === "running" ? "building a case…" : demo === "failed" ? "demo unavailable" : "demo"}
          </button>
        )}
      </header>

      <div className="stage">
        <div className="rail left">
          <Transcript live={turns} board={board} />
        </div>

        <section className="centre">
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
        </section>

        <div className="rail right">
          <WhereToFile board={board} />
          <FormToFill board={board} />
          <ReadyToSend board={board} caseId={caseId} />
          <Report board={board} />
        </div>
      </div>

      <FilingDrawer board={board} open={drawerOpen} onToggle={() => setDrawerOpen((o) => !o)} />
    </div>
  );
}
