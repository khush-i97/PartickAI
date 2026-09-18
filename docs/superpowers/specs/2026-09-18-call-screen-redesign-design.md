# Call screen redesign — Patrick centre stage

**Date:** 2026-09-18
**Status:** approved, implementing

## Problem

The call screen gives every panel roughly equal weight: a 300px rail, two
columns, five panels, and an avatar competing with all of it. The person you are
talking to is the smallest interesting thing on screen, and the payoff of the
whole product — *here is the office that handles this, here is its contact, here
is your form filled in* — is buried in a narrow right-hand column.

## Shape

Three zones plus a drawer.

```
┌──────────────┬───────────────────────────┬──────────────┐
│  Transcript  │                           │  Case file   │
│              │        ( avatar )         │              │
│  full        │        End call           │  Live        │
│  history     │     Patrick is listening  │  analysis    │
│              │                           │              │
└──────────────┴───────────────────────────┴──────────────┘
         ▲  Austin Police Department — form ready        (drawer tab)
```

- **Centre** is Patrick: avatar, call button, status, errors.
- **Left rail** is the transcript, scrolling, full history.
- **Right rail** is what Patrick extracted: case file facts, then live analysis
  underneath — its alert border should catch the eye mid-call.
- **Drawer** holds filing: authorities, their contact details, the filled form,
  and dispatch status. Hidden until there is something in it.

### Why a drawer

The brief asked for the avatar to dominate *and* for office details and filled
forms to be visible. Those compete for the same pixels. The drawer resolves it
in time rather than space: during the interview the screen is Patrick; filing
detail appears when it exists, which is also when it matters.

### Drawer behaviour

- Hidden entirely while there are no authorities and no searches.
- A peek tab appears as soon as a search starts or an authority lands, naming
  the top-ranked office and its form state.
- Auto-opens **once**, on the first authority found. After that the user owns
  it — no further automatic opening, so it cannot fight the person using it.
- Two tabs: **Filing** (authorities, contacts, forms, dispatches) and
  **Activity** (the tool log, which is diagnostic rather than something a caller
  needs, and does not deserve rail space).

## Components

| File | Change |
|---|---|
| `App.tsx` | new three-zone layout; owns drawer open/closed and the auto-open-once latch |
| `board/FilingDrawer.tsx` | **new** — absorbs `AuthorityFinder`, `FormReady`, `Dispatches`, `ToolLog` |
| `board/Panels.tsx` | keeps `Transcript`, `CaseFile`, `Inconsistencies`; exports `Panel` and shared helpers |
| `styles/base.css` | **new** — tokens, panel, typography, shared atoms |
| `styles/call.css` | **new** — call screen layout, avatar, drawer |
| `index.css` | removed, replaced by the two above |

No data-layer change. `useBoard` already returns every table the drawer needs.

## Constraints honoured

- **No router.** This is the call screen only. Landing and homepage come next
  and will introduce routing. `?case=<id>` review mode keeps working — with no
  live turns the transcript falls back to stored rows, and the drawer opens
  populated rather than animating in.
- **Same palette.** Noir background, desk-lamp amber accent, serif body,
  monospace labels. This is a layout change, not a rebrand.
- **Reduced motion.** The drawer's slide and the fact-highlight animation both
  respect `prefers-reduced-motion`.
- **Responsive.** Under 900px the grid stacks — avatar, transcript, extraction —
  and the drawer becomes a full-height sheet.

## Known gap: there is no address

The brief asked for each office's address. The `authorities` table has no such
column: it stores `name`, `handles`, `reason`, `email`, `phone`, `form_url`,
`source_url`. Real rows look like *Austin Police Department · 3-1-1 or
512-974-2000 · ireportaustin.com*.

The drawer therefore presents the contact details that exist, laid out properly
rather than crammed into one line. Showing a street address would need a schema
column plus an extraction change in `tools/authorities.py`, and is out of scope
here.

## Verification

No frontend tests exist, so this is verified against real data rather than
fixtures. Two cases in the project carry enough to exercise the drawer:

- `abe2224c-ee51-429a-af15-2eb2af02e4fb` — 3 authorities, 17 form fields
  (Austin, Texas scam_fraud) — exercises contacts and the filled form.
- `a0a95812-d4bb-4283-b74c-de4a11fa5b9f` — 3 authorities, 3 dispatches
  (Mumbai scam_fraud) — exercises dispatch status and the email viewer.

Open each at `?case=<id>`, confirm the drawer renders real contacts, real form
fields and real dispatch rows, and check the layout at desktop and at 375px.
`npm run build` must pass (it typechecks via `tsc --noEmit`).
