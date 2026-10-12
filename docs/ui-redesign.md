# Friendly AI studio redesign

## Direction

Keep the Local AI name and existing functionality. Give the web app a friendly,
colorful identity with a smiling speech-bubble mascot, rounded surfaces, warm
backgrounds, and violet, peach, mint, sky, and rose accents. Use existing Lucide
icons and system fonts; no new dependencies or external font requests.

The ui-ux-pro-max search matched playful claymorphism to creative tools. We use
its soft shapes and pastel palette with restrained depth so controls and long
AI answers remain readable. Its initial marketing-page/minimalism recommendation
did not fit this application and was not used.

## Implementation checkpoints

1. Shared identity: semantic light/dark tokens, original SVG logo, branded sign-in,
   sidebar, header, dashboard, focus styles, skip link, and reduced-motion support.
   Verified: TypeScript, 30 shared-component tests, targeted ESLint, diff check.
2. Chat: friendly empty state and editable starter prompts, readable conversation
   cards, clearer composer and agent controls, and responsive layout.
3. Acceptance: frontend regression suite, production build, theme contrast,
   desktop/mobile visual checks, and navigation/interaction smoke tests.

Backend agents, authentication, stored memory, and API contracts are outside the
redesign. Visual verification may use isolated synthetic API fixtures; that is
not a substitute for testing model inference.
