// The case board's data: one initial read, then InsForge Realtime pushes every
// change. No polling. The gateway writes rows; a Postgres trigger publishes
// each one on the channel case:<id> (see db/002_realtime_triggers.sql).
import { createClient } from "@insforge/sdk";
import { useEffect, useState } from "react";

export const insforge = createClient({
  baseUrl: import.meta.env.VITE_INSFORGE_URL,
  anonKey: import.meta.env.VITE_INSFORGE_ANON_KEY,
});

export type Row = Record<string, any> & { id: string };
export type Board = {
  cases: Row[];
  case_fields: Row[];
  transcript_turns: Row[];
  inconsistencies: Row[];
  tool_events: Row[];
  authority_searches: Row[];
  authorities: Row[];
  form_fields: Row[];
  dispatches: Row[];
};

const EMPTY: Board = {
  cases: [], case_fields: [], transcript_turns: [], inconsistencies: [],
  tool_events: [], authority_searches: [], authorities: [], form_fields: [], dispatches: [],
};
const TABLES = Object.keys(EMPTY) as (keyof Board)[];

function merge(rows: Row[], row: Row): Row[] {
  const i = rows.findIndex((r) => r.id === row.id);
  if (i === -1) return [...rows, row];
  const next = [...rows];
  next[i] = { ...next[i], ...row };
  return next;
}

export function useBoard(caseId: string | null): Board {
  const [board, setBoard] = useState<Board>(EMPTY);

  useEffect(() => {
    setBoard(EMPTY);
    if (!caseId) return;
    let alive = true;
    const channel = `case:${caseId}`;

    const onChange = (msg: { table: keyof Board; row: Row; meta?: { channel?: string } }) => {
      // InsForge reports the channel as "realtime:case:<id>", so match on the ending.
      if (!alive || !msg.meta?.channel?.endsWith(channel) || !(msg.table in EMPTY)) return;
      setBoard((b) => ({ ...b, [msg.table]: merge(b[msg.table], msg.row) }));
    };

    (async () => {
      await insforge.realtime.connect();
      const sub = await insforge.realtime.subscribe(channel);
      if (!sub.ok) console.error("realtime subscribe failed", sub.error);
      insforge.realtime.on("change", onChange);
      // Rows written before the subscription landed.
      for (const table of TABLES) {
        const key = table === "cases" ? "id" : "case_id";
        const { data } = await insforge.database.from(table).select("*").eq(key, caseId);
        if (alive && data) setBoard((b) => ({ ...b, [table]: (data as Row[]).reduce(merge, b[table]) }));
      }
    })();

    return () => {
      alive = false;
      insforge.realtime.off("change", onChange);
      insforge.realtime.unsubscribe(channel);
    };
  }, [caseId]);

  return board;
}
