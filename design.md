# Design — Mallow

A shared visual system for Mallow, a local AI workspace. Every route uses this
system. Extend this file when the system needs to grow; do not pick a new theme
per page.

## Genre

Playful, adapted for a focused productivity app: soft, rounded, curious, and
clear. The interface should feel friendly without making routine work feel
childish.

## Macrostructure family

- Marketing pages: none in the current app.
- App pages: Workbench — a clear working area with an optional contextual rail.
  Dashboard variations group destinations by job; task pages foreground their
  main editor, results, or list.
- Content pages: Catalogue — use for browsable collections such as documents
  and saved memories, with search and metadata kept close to each item.

The persistent sidebar is the app navigation. There is no marketing footer.
Routes, feature ownership, and information architecture remain in the Next.js
App Router.

## Theme — Bubble

Custom theme, tuned from the user's Bubble preference. Vibe: “soft bubbles,
pastel, cozy, curious mascot”. The palette keeps a lavender anchor on a lightly
tinted paper, with sea-glass and apricot reserved for distinct supporting
meanings. Accents stay on their own surfaces; they never blend into a gradient.

- `--color-paper`: `oklch(97% 0.014 295)`
- `--color-paper-2`: `oklch(94% 0.018 295)`
- `--color-paper-3`: `oklch(91% 0.022 295)`
- `--color-ink`: `oklch(23% 0.020 285)`
- `--color-ink-2`: `oklch(36% 0.022 285)`
- `--color-rule`: `oklch(82% 0.018 295)`
- `--color-rule-2`: `oklch(62% 0.020 295)`
- `--color-muted`: `oklch(48% 0.025 285)`
- `--color-neutral`: `oklch(42% 0.020 285)`
- `--color-accent`: `oklch(73% 0.14 292)`
- `--color-accent-ink`: `oklch(23% 0.020 285)`
- `--color-accent-2`: `oklch(76% 0.11 195)` (sea-glass)
- `--color-accent-3`: `oklch(80% 0.11 55)` (apricot)
- `--color-focus`: `oklch(35% 0.13 292)`
- `--color-error-ink`: `oklch(97% 0.014 295)` (light) / `oklch(23% 0.020 285)` (dark)
- `--color-mascot-fur`: `oklch(62% 0.09 50)`
- `--color-mascot-muzzle`: `oklch(92% 0.025 70)`
- Axes: light / rounded-sans / cool-violet

Dark mode uses plum-tinted surfaces and lighter lavender, sea-glass, and
apricot accents. Pure black and pure white are not base surfaces.

## Typography

- Display: `ui-rounded`, weight 600, roman.
- Body: `Avenir Next`, weight 400, with `ui-rounded` and `system-ui` fallbacks.
- Mono: the platform monospace stack, only for code and tabular technical data.
- Display tracking: `-0.025em`.
- No remote font requests; the app remains usable offline.

## Spacing and shape

Use the named 4-point spacing scale in `frontend/src/app/tokens.css` for new
shared styles. Existing Tailwind spacing utilities remain supported. Cards use
soft 16px corners, inputs 12px, and pills full rounding. Depth comes from a
single faint shadow or a tinted surface, not stacked shadows.

## Motion

- Easings: `--ease-out`, `--ease-in`, and `--ease-in-out` in `tokens.css`.
- Durations: micro 120ms, short 220ms, long 420ms.
- Motion communicates state: brief color/opacity changes and a 1px press on
  buttons. No bounce, scroll-triggered reveals, or ambient loops.
- Reduced motion removes spatial movement; functional loading indicators remain.

## Microinteractions

- Buttons, fields, tabs, links, and navigation have visible hover, focus,
  pressed, disabled, and loading states where applicable.
- Focus rings appear immediately and use the focus token.
- Keep success quiet when the saved result is already visible. Errors retain
  their text and icon cues; color alone never carries status.
- Tooltips open immediately on focus and use the provider's short hover delay.

## CTA voice

- Primary actions use a lavender fill, dark plum text, rounded corners, and a
  direct verb label.
- Secondary actions use a tinted or outlined surface.
- Buttons stay one line and at least 44px tall for touch.

## Brand

The working product name is **Mallow**, with “Local AI studio” as the
descriptive line. The mascot is a small, friendly otter rendered as a simple
vector mark. The shared mark is inline SVG so fur and line colors follow light
and dark themes; the browser icon uses a matching palette. Keep its expression
readable at sidebar and favicon sizes; do not add decorative emoji.

## What pages must share

- Mallow wordmark and otter mark.
- Bubble palette and semantic color roles.
- Rounded display and native body font stacks.
- Button, input, card, focus, and reduced-motion behavior.
- The existing routes, authentication, data fetching, and integrations.

## Exports

### `tokens.css`

The source of truth is [`frontend/src/app/tokens.css`](frontend/src/app/tokens.css).
The app entry stylesheet imports it before mapping the tokens into shadcn's
semantic variables.

### Tailwind v4 `@theme`

```css
@theme {
  --color-paper: oklch(97% 0.014 295);
  --color-paper-2: oklch(94% 0.018 295);
  --color-paper-3: oklch(91% 0.022 295);
  --color-ink: oklch(23% 0.020 285);
  --color-ink-2: oklch(36% 0.022 285);
  --color-rule: oklch(82% 0.018 295);
  --color-accent: oklch(73% 0.14 292);
  --color-accent-2: oklch(76% 0.11 195);
  --color-accent-3: oklch(80% 0.11 55);
  --color-error-ink: oklch(97% 0.014 295);
  --color-mascot-fur: oklch(62% 0.09 50);
  --color-mascot-muzzle: oklch(92% 0.025 70);
  --font-display: ui-rounded, "Avenir Next", system-ui, sans-serif;
  --font-body: "Avenir Next", ui-rounded, system-ui, sans-serif;
  --spacing-xs: 0.5rem;
  --spacing-sm: 0.75rem;
  --spacing-md: 1rem;
  --spacing-lg: 1.5rem;
  --spacing-xl: 2rem;
  --spacing-2xl: 3rem;
  --radius-card: 1rem;
  --radius-input: 0.75rem;
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --ease-in: cubic-bezier(0.7, 0, 0.84, 0);
  --ease-in-out: cubic-bezier(0.65, 0, 0.35, 1);
}
```

### DTCG `tokens.json`

```json
{
  "$schema": "https://design-tokens.github.io/community-group/format/",
  "color": {
    "paper": { "$value": "oklch(97% 0.014 295)", "$type": "color" },
    "paper-2": { "$value": "oklch(94% 0.018 295)", "$type": "color" },
    "paper-3": { "$value": "oklch(91% 0.022 295)", "$type": "color" },
    "ink": { "$value": "oklch(23% 0.020 285)", "$type": "color" },
    "rule": { "$value": "oklch(82% 0.018 295)", "$type": "color" },
    "accent": { "$value": "oklch(73% 0.14 292)", "$type": "color" },
    "accent-2": { "$value": "oklch(76% 0.11 195)", "$type": "color" },
    "accent-3": { "$value": "oklch(80% 0.11 55)", "$type": "color" },
    "focus": { "$value": "oklch(35% 0.13 292)", "$type": "color" },
    "error-ink": { "$value": "oklch(97% 0.014 295)", "$type": "color" },
    "mascot-fur": { "$value": "oklch(62% 0.09 50)", "$type": "color" },
    "mascot-muzzle": { "$value": "oklch(92% 0.025 70)", "$type": "color" }
  },
  "font": {
    "display": { "$value": "ui-rounded, Avenir Next, system-ui, sans-serif", "$type": "fontFamily" },
    "body": { "$value": "Avenir Next, ui-rounded, system-ui, sans-serif", "$type": "fontFamily" },
    "mono": { "$value": "ui-monospace, monospace", "$type": "fontFamily" }
  },
  "space": {
    "3xs": { "$value": "0.25rem", "$type": "dimension" },
    "2xs": { "$value": "0.5rem", "$type": "dimension" },
    "xs": { "$value": "0.75rem", "$type": "dimension" },
    "sm": { "$value": "1rem", "$type": "dimension" },
    "md": { "$value": "1.5rem", "$type": "dimension" },
    "lg": { "$value": "2rem", "$type": "dimension" },
    "xl": { "$value": "3rem", "$type": "dimension" }
  }
}
```

### shadcn/ui CSS variables

The app's light/dark mappings live in `frontend/src/app/tokens.css`; the
semantic names are `--background`, `--foreground`, `--card`, `--primary`,
`--secondary`, `--muted`, `--border`, `--input`, and `--ring`.

## Hallmark record

<!-- Hallmark · pre-emit critique: P4 H5 E4 S5 R4 V4 -->
<!-- Hallmark · genre: playful · macrostructure: Workbench · theme: Bubble ·
     mascot: otter · nav: N3 side-rail · footer: none · enrichment: none -->
