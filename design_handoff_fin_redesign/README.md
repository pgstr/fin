# Handoff: Fin UI-Redesign (Terminal-Dense, Dark/Light)

## Overview
Complete visual redesign of **Fin** (github.com/pgstr/fin), a German-first, local-first household financial planner (FastAPI + Jinja2 + one CSS file + SQLite). The redesign replaces the purple dark theme with a dense, terminal-inspired system: neutral anthracite dark mode + cool light mode (one token set, user-switchable), pastel colors reserved for data visualization, clear green/red for amounts, and a peach "F" block brand mark with monospace breadcrumbs.

## About the Design Files
The files in this bundle are **design references created in HTML** (Design Component prototypes). They show intended look and behavior — they are **not production code to copy directly**. The task is to recreate these designs in the target codebase: `src/finanzplaner/templates/*.html` (Jinja2) and `src/finanzplaner/static/app.css`, keeping the existing server-rendered architecture. No JS framework is needed — the current vanilla `app.js` approach is sufficient (plus a small theme-toggle script, see below).

## Fidelity
**High-fidelity.** Colors, typography, spacing, and component treatments are final. Recreate pixel-perfectly. All copy is German and matches the existing i18n keys in `src/finanzplaner/i18n.py` (labels shown in the mocks are the existing translations or shortened variants of them).

## Architecture Mapping (design file → Jinja template)
| Design file | Target template |
| --- | --- |
| Übersicht.dc.html | overview.html (+ base.html shell) |
| Buchungen.dc.html | transactions.html |
| Buchungsdetails.dc.html | transaction_detail.html |
| Prognose.dc.html | forecast.html |
| Kategorietrends.dc.html | trends.html |
| Import.dc.html | import.html |
| Kategorien.dc.html | categories.html |
| Einstellungen.dc.html | settings.html |
| Agent-Zugänge.dc.html | tokens.html |
| Benutzer.dc.html | users.html |
| Anmelden.dc.html / Einrichten.dc.html | login.html / setup.html |
| Mobil *.dc.html | responsive breakpoints of the same templates (≤860px) |
| Design-System.dc.html | token + component reference |
| Zustände.dc.html | empty/error states reference |

## Design Tokens (CSS custom properties)
Define once on `:root` (dark = default) and override under `[data-theme="light"]` on `<html>`.

Dark (default):
```css
--bg:#101418; --panel:#171c23; --field:#10151b;
--line:rgba(150,165,180,.14); --line2:rgba(150,165,180,.28);
--track:rgba(150,165,180,.12); --hair:rgba(150,165,180,.08);
--ink:#e6ebf1; --mut:#8a97a5;
--acc:#f5c79a; --accSoft:rgba(245,199,154,.14);
--brand:#f5c79a; --brandInk:#101418;
--pos:#35cd7c; --neg:#f2505f;
--sky:#a9cdf2; --mint:#9fe0bf; --peach:#f5c79a; --rose:#f0aab8; --lav:#cbbcf0;
```
Light (`[data-theme="light"]`):
```css
--bg:#f5f6f8; --panel:#fff; --field:#f8f9fb;
--line:#e4e8ee; --line2:#d6dbe3; --track:#eef1f5; --hair:#eef1f5;
--ink:#1a212b; --mut:#6b7684;
--acc:#c07a33; --accSoft:rgba(232,168,106,.16);
--brand:#e8a86a; --brandInk:#fff;
--pos:#149447; --neg:#d93848;
--sky:#88b6e0; --mint:#8fd4b1; --peach:#e8a86a; --rose:#e79cac; --lav:#b7a6e3;
```
**Color rules:**
- `--pos`/`--neg` ONLY for monetary amounts and deltas (incoming green, outgoing red, ▲/▼ indicators, destructive actions in `--neg`).
- `--sky`/`--mint`/`--peach`/`--rose`/`--lav` ONLY for chart lines, forecast bands, and category bars (assign one pastel per category bar, rotating).
- `--acc` (peach) for: brand, active nav, month selector, UNKAT warnings, text links, breadcrumb current segment, forecast dashes.

## Typography
- UI text: **Archivo** (Google Fonts, 400–700). Body .8rem; H1 1.15rem/600; panel titles .78rem/uppercase/letter-spacing .1em in `--mut`.
- Numbers, labels, meta, buttons: **IBM Plex Mono** (400/500/600). Big KPI number 1.25rem/600; table meta .64–.7rem uppercase letter-spacing .1em.
- All amounts: German formatting `1.842,60`, minus as `−` (U+2212), plus `+`, tabular by nature of the mono font.

## Layout / Shell
- **Icon rail** (desktop): 3.5rem wide, `--panel` bg, right border `--line`. Top: 2.1rem brand square (bg `--brand`, mono "F", radius .35rem). Nav icons 2.3rem squares, radius .4rem; active = bg `--accSoft` + color `--acc`; hover = bg `--track`. Nav order: ◫ Übersicht, ↕ Buchungen, ⌁ Prognose, ∿ Kategorietrends, ↓ Import, # Kategorien. ("Wiederkehrend" intentionally removed from nav.)
- **User menu**: avatar circle (2.1rem, `--accSoft`/`--acc`, initial) pinned to rail bottom; click opens popover (left of avatar: min-width 11.5rem, `--panel`, border `--line2`, radius .4rem, shadow 0 10px 30px rgba(0,0,0,.25)) containing Einstellungen ⚙, Agent-Zugänge ◇, Benutzer ○, Abmelden →. Current page highlighted with `--accSoft`/`--acc`. These three pages are NOT in the rail.
- **Top strip**: .55rem/1.4rem padding, `--panel` bg, bottom border. Mono breadcrumb `FIN / HAUSHALTSKONTO / 2026-05` (current segment `--acc`), right side: sync dot (`--pos`) + timestamp, theme toggle (☾/☀ pill), username.
- **Content**: padding 1.1rem 1.4rem 2rem; panels = `--panel` bg, 1px `--line` border, radius .4rem, padding .9rem 1rem, gap .5rem between panels. Dense 6-column KPI grid on Übersicht; chart 1.7fr / side panel 1fr.
- **Mobile (≤860px)**: sticky top header (brand square + title + toggle), content single column, fixed bottom nav with 5 items (min-height 3.4rem ≈ 54px targets): Übersicht, Buchungen, Prognose, Trends, Mehr; active item `--acc`.

## Components (see Design-System.dc.html rendered for reference)
- **KPI tile**: label .64rem uppercase `--mut`; mono value 1.25rem/600; delta line .68rem in `--pos`/`--neg`/`--acc`.
- **Chips**: mono .68rem, .05rem .4rem padding, radius .25rem, 1px border. Category = `--line2`/`--mut`; UNKAT = `--acc`; AKTIV = `--pos`; REVOKED = `--line2`/`--mut`.
- **Buttons**: primary = `--brand` bg, `--brandInk` text, mono .7rem 600 uppercase, radius .35rem, padding .5rem .8rem. Secondary = transparent, 1px `--line2`, hover border/text `--acc`. Text links = mono `--acc` with `→`. Destructive = mono `--neg`.
- **Inputs**: `--field` bg, 1px `--line2`, radius .35rem, .5rem .65rem padding; label above in .64rem uppercase mono-ish 600 `--mut`.
- **Tables**: header mono .64rem uppercase `--mut` with 1px `--line` bottom; rows .5rem vertical padding, `--hair` row dividers, hover bg `--hair`; date column mono `--mut`; amount column right-aligned mono in `--pos`/`--neg`. Sortable headers: clickable, active column in `--acc` with ↑/↓.
- **Category bars**: 6px track `--track` radius 3px, fill = pastel per category; mono label + right-aligned amount + % column.
- **Charts (SVG)**: horizontal gridlines `--track` dashed-none 1px; actual line `--sky` 2px; forecast line `--peach` 2px dashed 5 5; uncertainty band polygon `--accSoft`; axis labels mono 9px `--mut`; legend `━ IST` / `┄ PROGNOSE`. Tooltip on data points: small `--panel` box, border `--line2`, mono .66rem, e.g. `MAI · 1.842,60 · IST`.
- **Notice bars**: .45–.5rem padding, 3px left border (`--acc` info / `--pos` success / `--neg` error), `--field`/`--panel` bg, .72–.76rem text; mono prefix (OK / FEHLER / HINWEIS).
- **Empty states**: centered icon + bold .86rem line + `--mut` explainer + primary or secondary action (see Zustände.dc.html: no account, unreliable balance, no forecast, filter empty, import errors, one-time token).

## Interactions & Behavior
- **Theme toggle**: ☾/☀ pill in top strip (and a Darstellung radio in Einstellungen). Persist in `localStorage("fin-theme")`, apply `data-theme` on `<html>` before first paint (inline script in `<head>` to avoid flash). Default: dark (or `prefers-color-scheme`).
- **Month switcher**: `‹ APR | MAI 2026 | JUN ›` segmented mono control; current month bordered `--acc`; future months disabled at 45% opacity with tooltip. Switching swaps all data on the page (server round-trip via `?month=` as today).
- **Table sorting** (Buchungen): click header toggles asc/desc; indicator ↑/↓; default date desc.
- **Chart tooltips**: pointerenter on data points shows tooltip anchored above point (existing `app.js` tooltip logic can be reused; restyle only).
- Hover states: rows `--hair`; nav icons `--track`; buttons as above. Transitions ≤ .16s ease, none on charts.

## State Management
Server-rendered as today. Client-side state is only: theme (localStorage), open/closed user-menu (details element), chart tooltip, and (optional progressive enhancement) table sort.

## Assets
No image assets. Fonts: Archivo + IBM Plex Mono via Google Fonts (self-host for the local-first deployment). Icons are unicode glyphs (◫ ↕ ⌁ ∿ ↓ # ⚙ ◇ ○ ☾ ☀ ▲ ▼ ‹ › →) — replace with an icon set of the codebase's choice if preferred, keeping the 2.3rem hit areas.

## Files
- `Übersicht.dc.html`, `Buchungen.dc.html`, `Buchungsdetails.dc.html`, `Prognose.dc.html`, `Kategorietrends.dc.html`, `Import.dc.html`, `Kategorien.dc.html`, `Einstellungen.dc.html`, `Agent-Zugänge.dc.html`, `Benutzer.dc.html`, `Anmelden.dc.html`, `Einrichten.dc.html` — desktop screens
- `Mobil Übersicht.dc.html`, `Mobil Buchungen.dc.html`, `Mobil Prognose.dc.html` — mobile
- `Design-System.dc.html` — tokens, type, components
- `Zustände.dc.html` — empty & error states
- `support.js` — prototype runtime (ignore; not part of the design)

Open any `.dc.html` in a browser to see the live design; the ☾/☀ toggle switches themes in every file.
