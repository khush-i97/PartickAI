# CLAUDE.md

Context for anyone (human or agent) picking up this repo. For InsForge backend
specifics, see [AGENTS.md](AGENTS.md).

## What we are building

**Patrick** — a voice intake desk. A person calls **Detective Patrick**, tells
him what went wrong in their own language, and by the end of the call a real
complaint has been filed with the real organizations that handle it.

The problem it solves: people who have been scammed, ignored by a landlord, or
wrongly billed usually know what happened but not *who to tell*, in what format,
or what details that office needs. Patrick does the interview, finds the right
offices by live web search, fills their forms, and sends the reports.

One call produces: a structured case file, an English transcript of a call that
may have been in any language, a list of real authorities with source URLs, and
a dispatched report per authority.

## Architecture

Three pieces. The gateway is the only part that holds secrets.

```
browser (Vite/React)  ──ws──►  gateway (FastAPI)  ──ws──►  Boson Higgs (voice)
        │                          │
        │                          ├──► OpenAI / Model Gateway (all text reasoning)
        │                          ├──► Tavily (live authority search)
        │                          └──► InsForge (Postgres, storage, email)
        │                                     │
        └────────────── InsForge Realtime ◄───┘   (board updates, no polling)
```

The browser never talks to the voice model or any API key. It opens one
websocket to the gateway and otherwise just *watches the database*: the gateway
writes rows, a Postgres trigger publishes them on channel `case:<id>`, and the
board re-renders. That is why panels fill in on their own during a call.

### Two models, on purpose

| Model | Env | Job |
|---|---|---|
| Boson Higgs Realtime | `BOSON_API_KEY` | ears and mouth — streaming audio both ways |
| OpenAI (default `gpt-5.4-mini`) | `OPENAI_API_KEY` | every structured-reasoning step |

All text work funnels through one function, `insforge.llm_json()`, so the voice
model is never blocked waiting on JSON. Falls back to the InsForge Model Gateway
(OpenRouter) when `OPENAI_API_KEY` is unset.

⚠️ `llm_json` sends `temperature: 0`. **GPT-5.5 and newer reasoning models reject
that with a 400**, and run 2–3x slower, which matters because the scribe call
runs on every caller turn. Stay on a model that accepts `temperature: 0`.

## Layout

```
gateway/           FastAPI voice gateway — the whole backend
  main.py          app, CORS, /health, /ws/call (checks Origin by hand)
  relay.py         CallSession: browser ⇄ Higgs relay, the "scribe" loop  ← biggest file
  patrick.py       character prompt + Higgs session config
  insforge.py      REST client for InsForge + llm_json (single LLM chokepoint)
  mailer.py        the ONLY code path that sends email; enforces safe mode
  redact.py        strips card numbers and spoken passwords before storage
  tools/           the nine tools Patrick can call
frontend/src/
  App.tsx          call button, status, panel layout
  board/Panels.tsx the six live panels
  board/Avatar.tsx video avatar, reacts to voice level and mood
  audio/           mic capture, resampling, AudioWorklets
  lib/board.ts     initial read + realtime subscription
db/                four SQL migrations + cached authority fallback
routing.yaml       case types → what kind of office handles them, and what each needs
Dockerfile         builds the gateway (root, because it reads routing.yaml + db/)
```

### Patrick's tools (`gateway/tools/`)

Guidance lives in each tool's *description*, not the prompt — Boson's own tutorial
found a long behavioural prompt stopped the model calling tools at all.

| Tool | What it does |
|---|---|
| `update_case_file` | write one fact (name, amount, when…) |
| `flag_inconsistency` | record a contradiction to raise kindly |
| `classify_case` | pick one case type from `routing.yaml` |
| `lookup_transactions` | read the mock bank; catches the planted mismatch |
| `find_authorities` | Tavily search → LLM picks the one official org |
| `propose_filing` | summarize for the caller to approve |
| `file_case` | fill each authority's form and send |
| `send_confirmation` | email the caller their copy |
| `emergency_stop` | halt intake, tell them to call emergency services |

## What is implemented

- **Any-language calls.** Patrick answers in the caller's language and mirrors
  code-switching (Hinglish stays Hinglish). Language is pinned once detected —
  Higgs drifts back to English otherwise.
- **Live case file.** Facts land as the caller says them, no end-of-call form.
- **Contradiction catching.** Two layers: the scribe compares each turn against
  what was said before, and `bank.py` diffs the story against bank records *in
  code*, so a skimming voice model cannot miss it. Genuine corrections
  ("sorry, actually…") are not treated as conflicts.
- **Real authority lookup.** Tavily search per destination in `routing.yaml`,
  then an LLM picks the one official org under a strict source rule: the URL
  must be the organization's *own* domain. News, blogs, directories and law
  firms are rejected. Falls back to `db/cached_authorities.json`.
- **Real form filling.** Reads the authority's actual complaint form and maps
  case fields onto its inputs.
- **Explicit consent.** Nothing sends until the caller says yes; a separate LLM
  pass decides whether they actually agreed and which orgs to drop.
- **Safe mode.** `SAFE_MODE` anything-but-`false` means real recipients are never
  mailed — everything goes to the demo inboxes, enforced in `mailer.py`, not in
  a prompt. Every mail names the real intended recipient and the source URL.
- **Redaction.** Card numbers and spoken passwords are masked before anything is
  stored, shown or emailed. Best-effort: digits spoken as words are not caught.
- **Emergency stop.** Danger → tell them to call emergency services, stop intake.
- **Live board.** Six panels driven by realtime: transcript, case file,
  inconsistencies, authority finder, dispatches, tool log.
- **Read-only review.** `?case=<id>` replays a finished case.

## 🔨 Current work: UI redesign

**This is the active workstream — landing page, homepage, and the whole look.**

Today the app opens straight onto the call board: `App.tsx` renders a header,
the avatar and call button, and five panels in three columns. There is no
landing page, no explanation of what Patrick is, and no marketing surface —
a first-time visitor sees a dark grid of empty panels and one button.

Planned:
- A **landing page** that explains the product before asking anyone to talk.
- A **homepage / entry flow** separate from the live call board.
- A **visual redesign** across the app.

Notes for whoever takes this:
- All styling is one file, `frontend/src/index.css`, and the markup is plain
  semantic elements with class names — no CSS framework, no component library.
- There is **no router** yet. Adding distinct landing/home/call views means
  introducing routing (or conditional rendering) in `App.tsx`. The only existing
  URL-based state is `?case=<id>`; keep that working.
- `Avatar.tsx` plays video from `frontend/public/avatar/` and reacts to voice
  level and mood — it is the main visual character, worth designing around.
- The panels in `Panels.tsx` are the product's "proof" surface. They look empty
  before a call; a redesign should consider that first-run state.

### Good parallel work (not the redesign)

Pick these up to avoid colliding with the UI work:
- **Demo inboxes.** `DEMO_AUTHORITY_INBOX` / `DEMO_CALLER_INBOX` are unset, locally and on
  InstaCloud, so every dispatch shows *Blocked by safe mode* and no email has been delivered yet.
- **Evals.** `eval_runs` / `eval_results` tables exist and are empty — no
  harness has been written.
- **Redaction gaps.** Digits spoken as words ("four five one two") pass through.
- **Tests.** Only `mailer.py` is covered — 19 tests, all in
  `gateway/tests/test_mailer.py`. `relay.py` and the tools have none.

## Running it

```bash
cp .env.example .env    # then fill in the keys
```

Gateway (needs the venv; `uvicorn main:app --reload --port 8000` from `gateway/`):

```bash
cd gateway && .venv/bin/uvicorn main:app --reload --port 8000
```

Frontend:

```bash
npm --prefix frontend run dev
```

Then open http://localhost:5173 and click **Call Patrick** (needs mic permission).

Tests: `gateway/.venv/bin/python -m pytest gateway -q`

### Local gotchas

- **TLS.** If Python has no system CA bundle, the Boson websocket fails with
  `CERTIFICATE_VERIFY_FAILED` while `httpx` still works (it bundles its own).
  Export `SSL_CERT_FILE=$(python -c 'import certifi;print(certifi.where())')`.
- **HTTP 431 on :5173.** Too many cookies scoped to `localhost` overflow Node's
  16KB header cap. Run Vite with `NODE_OPTIONS=--max-http-header-size=81920`, or
  clear localhost cookies.
- **Stuck on "Connecting…" forever.** Same cookie pile, different victim: the
  `/ws/call` handshake carries it too, and uvicorn's default `websockets`
  implementation caps a header line at 8KB, so the upgrade is refused and no
  `ready` event ever arrives. The gateway log shows
  `431 Request Header Fields Too Large`. Run uvicorn with `--ws wsproto`
  (`pip install wsproto`), which routes the handshake through h11 and honours
  `--h11-max-incomplete-event-size 262144`. Dev-only: deliberately **not** in
  `requirements.txt`, because the real cause is one browser's localhost cookies,
  not anything about production.
- **Origin check.** `/ws/call` rejects any origin not in `ALLOWED_ORIGINS`
  (CORS middleware does not cover websockets, so `main.py` checks by hand).
  A deployed frontend must be added there or every call fails at handshake.

## Deployment

**Status: both sides are live.**

- Frontend: https://patrick.insforge.site (InsForge Sites; also `6zdyfp34.insforge.site`).
- Gateway: InstaCloud compute service `gateway`, always on, WebSocket mode:
  `https://prod-main-gateway-13fb63-00pa4t2ctjb.compute.instacloud-edge.com`
  (`/health`, `/ws/call`). It is **not** on InsForge compute or Fly.

Redeploy:

1. **Gateway** → from the repo root: `insta --agent deploy . --port 8080 --websocket`.
   The build is remote (root `Dockerfile`); no local Docker needed. Secrets are set
   with `insta --agent secrets set NAME` (value on stdin), and setting one redeploys.
   A redeploy drops calls in progress.
2. **`ALLOWED_ORIGINS`** (an InstaCloud secret) must include the deployed site, or
   the websocket handshake is refused.
3. **Frontend** → `npx -y @insforge/cli deployments deploy ./frontend`, then
   `npx -y @insforge/cli deployments status <id> --sync` until READY. The build is
   only promoted when its status is synced. Do not pipe the deploy command through
   `grep` or `tail`; that kills it mid deploy. Build variables are set with
   `deployments env set` (`VITE_GATEWAY_URL`, `VITE_INSFORGE_URL`, `VITE_INSFORGE_ANON_KEY`).

## Conventions

- Comments explain *why*, not what, and are written for a reader who does not
  know the tradeoff. Match that tone.
- Secrets live in `.env` (gitignored) and are read via `os.environ` in the
  gateway only. Never a `VITE_*` var, never committed.
- InsForge specifics: inserts take an array — `insert([{...}])`; reference users
  as `auth.users(id)`; use `auth.uid()` in RLS. Storage uploads: keep both the
  returned `url` and `key`.
- Safety rules are enforced in code, not in prompts. If a new rule matters,
  put it where the model cannot talk its way past it.
