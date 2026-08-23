# Design System — SIH Smart Timetable Generator

**Status:** Proposed via `/design-consultation` (2026-08-23), preview generated and shown — not yet confirmed as final. Written to a file at the user's request before the approval step completed, so this is the working proposal, not a shipped lock-in. Revisit before building against it if anything below should change.

## Product Context
- **What this is:** A CP-SAT-based timetable generator for a university (Phase B: rebuild a minimal, non-wizard frontend — upload data, watch a solve run, view the resulting timetable grid).
- **Who it's for:** A college admin or faculty member evaluating/using the tool — not a consumer, not a marketing audience.
- **Space/industry:** Academic scheduling software (NEP 2020 / USAR, GGSIPU context — see `PLAN.md`/`FINAL_PLAN.md`).
- **Project type:** Internal utility tool / dashboard.
- **The one thing to feel:** *"This is serious, institutional software"* — not another impressive-looking demo. The prior 16-step wizard was elaborate but broke on first real use; this rebuild should read as engineered and trustworthy, not decorative.

## Research Notes
- TimeEdit (market leader in academic scheduling software, 200+ institutions) markets itself with purple gradients, rounded pill buttons, and consumer-SaaS visual energy — closer to a startup landing page than institutional software. Treated as the thing to deliberately not look like.
- FET (open-source timetabling tool) was inaccessible (Cloudflare-blocked) during research; not used as a direct reference.
- Category table stakes (every scheduling tool converges on this): a dense day×period grid, colored/labeled blocks, minimal chrome around the data itself.

## Aesthetic Direction
- **Direction:** Industrial / Utilitarian — function-first, data-dense, muted palette, monospace accents.
- **Decoration level:** Minimal. No illustration, no gradients, no decorative elements — typography and structure carry everything.
- **Mood:** Precision instrumentation, not a demo. Every choice should reinforce that the underlying CP-SAT solver is rigorous engineering, not a flashy toy.
- **Reference sites:** TimeEdit (timeedit.com) — used as a negative reference (what not to look like), not a positive one.

## Typography
- **Display/Hero (masthead only):** Cabinet Grotesk (700/500) — confident, clean grotesk, used sparingly (page title only), not for body text.
- **Body/UI:** Source Sans 3 — document-heritage sans, avoids the "generic AI dashboard" feel of Inter/Roboto/system-ui.
- **Data/Tables:** IBM Plex Mono with `tabular-nums` — used for *all* data: timetable cells, offering/course/room/faculty IDs, status numbers, time budgets. Not just code. This is the aesthetic's signature move: it makes the solver's output look like lab-instrument readings.
- **UI/Labels:** Same as body (Source Sans 3), except numeric fields which use the mono/tabular-nums treatment.
- **Loading:** Source Sans 3 + IBM Plex Mono via Google Fonts; Cabinet Grotesk via Fontshare's CDN (`api.fontshare.com`) — not on Google/Bunny Fonts.
- **Scale:** Masthead 18–34px (Cabinet Grotesk 700), body 14–15px, data/mono 11–13px, eyebrow/section labels 11px uppercase tracked +0.08–0.12em (IBM Plex Mono).

## Color
- **Approach:** Restrained — one accent, warm neutrals, muted semantic colors. Never the ubiquitous SaaS green-accent/cool-gray default, never TimeEdit-style purple.
- **Primary (Ink Navy):** `#1a2744` (deep variant `#0f1830`, mid variant `#2c3e63`) — the sole accent, used for the masthead bar, primary buttons, headings, table headers.
- **Background (Parchment):** `#f4f0e6`, with `#ece5d3` (deeper parchment, used for table headers/status panels) and `#faf8f2` (paper, used for cards) — warm, not stark white/cold gray.
- **Text (Ink):** `#1f1c14` primary, `#6b6455` muted.
- **Border:** `#d8d0bc` — warm, low-contrast hairlines.
- **Semantic — Warning (Ochre):** `#a3721f` on `#f3e6c8` background.
- **Semantic — Error (Brick):** `#8c3a2b` on `#f1ddd6` background.
- **Semantic — Solved/OK:** `#3d5a3d` on `#e2ead9` background. (Muted forest, not a bright consumer-app green — reserved for solve-success states only, never used as the primary brand accent.)
- **Dark mode:** Full palette inversion (see `[data-theme="dark"]` block in the preview file) — navy becomes a light ink-blue (`#c3cfe8`) against near-black warm backgrounds (`#171512`/`#0e0c0a`), semantic colors desaturate slightly. Not just a CSS filter — each token has an explicit dark-mode value.

## Spacing
- **Base unit:** 4px.
- **Density:** Compact — this is a data tool, not a marketing site. Generous whitespace would work against the "precision instrumentation" mood.
- **Scale:** 2xs(2) xs(4) sm(8) md(16) lg(24) xl(32) 2xl(48).

## Layout
- **Approach:** Grid-disciplined — strict columns, predictable alignment, echoing the timetable grid itself (the core content the whole page exists to show).
- **Grid:** App shell uses a fixed sidebar/status-column + main content pattern (e.g. 280px upload panel + flexible main column in the solve screen); breaks to single column under ~820px.
- **Max content width:** ~1180px.
- **Border radius:** 0 everywhere. Sharp corners on every card, button, input, and table cell — a deliberate departure from the near-universal rounded-SaaS look, reinforcing the industrial register.

## Motion
- **Approach:** Minimal-functional only. Motion exists solely to aid comprehension of state changes already inherent to the product (a status panel updating during a poll, a blocker list appearing after a failed pre-check) — never decorative, never for its own sake.
- **Easing/Duration:** Not yet specified in detail — defer to implementation; keep transitions short (150–250ms) and purely functional (opacity/height for appearing content, no bounce/spring effects).

## Deliberate Risks (where this system gets its own face)
1. **Navy + parchment instead of the near-universal green-accent/cool-gray SaaS default** (which the old, since-removed wizard also used). Costs some "modern dashboard" familiarity; gains an instant institutional signal that separates this from every generic admin-panel template.
2. **Monospace for all data, not just code/IDs.** Less common than proportional tabular-nums in most dashboards; makes every solver output (objective values, time budgets, room/faculty codes) read like precision-instrument telemetry, reinforcing trust in the solver's rigor.
3. **Zero border-radius everywhere.** Can read as "less finished" to eyes calibrated on rounded SaaS cards; reinforces the industrial/utilitarian register and visually differentiates from both TimeEdit's rounded-pill aesthetic and the old wizard's rounded-card look.

## Preview Artifact
- HTML preview generated and opened at `/tmp/design-consultation-preview-sih.html` (font specimens, color swatches, component samples, and a realistic upload+solve+timetable-grid mockup with light/dark toggle). Not yet formally approved — review before building the real frontend against these tokens.

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-08-23 | Industrial/Utilitarian aesthetic, navy+parchment, Cabinet Grotesk/Source Sans 3/IBM Plex Mono, zero border-radius, minimal motion | Proposed via `/design-consultation` for Phase B's frontend rebuild; approved through the preview-generation step, written to file before final sign-off at user's request |
