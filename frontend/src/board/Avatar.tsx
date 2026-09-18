import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

// Patrick's face, made with Higgs Avatar (gateway/avatar/render.py). Higgs Avatar
// needs about five seconds before its first frame, so it cannot lip sync a live
// call. Instead the clips are pre-rendered and the face is driven in real time by
// the loudness of Patrick's live voice: the talking clip shows and runs only while
// sound is actually playing, and the listening clip takes over in his pauses.
// A serious clip is used while a conflict is open. Hidden if no clips exist.
const CLIPS = { warm: ["/avatar/talk1.mp4", "/avatar/talk2.mp4"], serious: ["/avatar/serious1.mp4"] };

export type AvatarHandle = { voice: (rms: number) => void };

export const Avatar = forwardRef<AvatarHandle, { live: boolean; mood: "warm" | "serious" }>(({ live, mood }, ref) => {
  const [missing, setMissing] = useState(false);
  const [clip, setClip] = useState(CLIPS.warm[0]);
  const box = useRef<HTMLDivElement>(null);
  const idle = useRef<HTMLVideoElement>(null);
  const talking = useRef<HTMLVideoElement>(null);
  const state = useRef({ talking: false, quietSince: 0, turn: 0, mood });
  state.current.mood = mood;

  useImperativeHandle(ref, () => ({
    // Runs about 20 times a second, so it touches the DOM directly and never re-renders.
    voice(rms: number) {
      const s = state.current;
      const now = performance.now();
      const loud = rms > 0.012;
      if (loud) s.quietSince = 0;
      else if (!s.quietSince) s.quietSince = now;
      const shouldTalk = loud || (s.talking && now - s.quietSince < 220); // ride over gaps between words
      if (shouldTalk !== s.talking) {
        s.talking = shouldTalk;
        box.current?.classList.toggle("speaking", shouldTalk);
        if (shouldTalk) talking.current?.play().catch(() => {});
        else talking.current?.pause();
        if (!shouldTalk && now - s.quietSince > 200) {
          // A real pause: next sentence may use another take, or the serious one.
          const pool = CLIPS[s.mood];
          setClip(pool[++s.turn % pool.length]);
        }
      }
      // Louder speech, livelier face.
      if (talking.current && shouldTalk) talking.current.playbackRate = Math.min(1.25, 0.9 + rms * 3);
    },
  }));

  useEffect(() => {
    if (live) idle.current?.play().catch(() => {});
    else {
      idle.current?.pause();
      talking.current?.pause();
      box.current?.classList.remove("speaking");
      state.current.talking = false;
    }
  }, [live]);

  if (missing) return null;
  return (
    <>
      <div ref={box} className={`avatar ${live ? "live" : ""}`}>
        <video ref={idle} src="/avatar/idle.mp4" muted loop playsInline preload="auto" onError={() => setMissing(true)} />
        <video ref={talking} className="talk" src={clip} muted loop playsInline preload="auto"
               onError={() => setClip(CLIPS.warm[0])} />
      </div>
      <p className="avatar-note">AI avatar · Higgs Avatar</p>
    </>
  );
});
