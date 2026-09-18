import { useEffect, useRef, useState } from "react";

// Patrick's face, made with Higgs Avatar (gateway/avatar/render.py). The clips
// are pre-rendered and muted: his voice is live from Higgs Realtime, and a live
// avatar would add about five seconds per reply. Hidden if no clips exist.
const TALK = ["/avatar/talk1.mp4", "/avatar/talk2.mp4"];

export function Avatar({ speaking, live }: { speaking: boolean; live: boolean }) {
  const [missing, setMissing] = useState(false);
  const [talk, setTalk] = useState(0);
  const idle = useRef<HTMLVideoElement>(null);
  const talking = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (speaking) {
      setTalk((n) => (n + 1) % TALK.length);
      talking.current?.play().catch(() => {});
    } else {
      talking.current?.pause();
    }
  }, [speaking]);

  useEffect(() => {
    if (live) idle.current?.play().catch(() => {});
    else idle.current?.pause();
  }, [live]);

  if (missing) return null;
  return (
    <>
    <div className={`avatar ${live ? "live" : ""} ${speaking ? "speaking" : ""}`}>
      <video ref={idle} src="/avatar/idle.mp4" muted loop playsInline preload="auto" onError={() => setMissing(true)} />
      <video ref={talking} className="talk" src={TALK[talk]} muted loop playsInline preload="auto" />
    </div>
    <p className="avatar-note">AI avatar · Higgs Avatar</p>
    </>
  );
}
