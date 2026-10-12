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
   Includes accessible memory review, mobile drawer dismissal, labeled specialist
   inputs, new-chat scroll reset, and consistent page headers. Verified: full
   frontend suite (323 tests), TypeScript,
   targeted ESLint (no errors), and focused specialist/scroll/contrast tests.
3. Acceptance: frontend regression suite, production build, theme contrast,
   desktop/mobile visual checks, and navigation/interaction smoke tests.
   Complete: 323 frontend tests pass; the final typography changes pass 80 focused
   chat/RAG/SQL tests; TypeScript and the webpack production build pass. Targeted
   ESLint has no errors. Existing React test `act(...)` warnings and the attachment
   preview's `<img>` lint warning remain.

## Visual acceptance

Safari checks used an isolated local API/WebSocket fixture server, with no real
credentials, accounts, memories, or model calls. Desktop screenshots and exact
375 × 812 and 812 × 375 iframe viewports verified the light/dark styling, chat
greeting, message rendering, editable starter prompt, keyboard dialog dismissal
and focus return, mobile drawer dismissal, landscape composer reachability,
Documents, RAG Search, Memory, and Settings. Both temporary servers were stopped
and the preview tab was closed afterward.

Real-device mobile testing, automated Playwright execution, native meeting
capture, and live model inference were not rerun for this frontend redesign.
Reduced-motion support is defined in the shared stylesheet; OS preference
emulation was not exercised in Safari.

## Browser findings addressed

- Sign-in now spans the sidebar provider's flex wrapper instead of occupying a
  narrow column at the left edge.
- Empty chats reset the actual Radix scroll viewport to the greeting. Responses
  scroll to the bottom; the previous code targeted the non-scrolling wrapper.
- Short landscape viewports can scroll the whole chat page to reach the composer.
- Mobile navigation closes on selection and includes an explicit drawer toggle.
- The memory-review dialog traps focus, supports Escape, and returns focus to the
  composer. Its API validation and error handling are preserved.
- Text pairs meet 4.5:1 contrast in both themes; input boundaries meet 3:1 against
  the background and card surfaces. Regression tests read the actual CSS tokens.
- The Next.js starter favicon is replaced by the original mascot SVG.

Backend agents, authentication, stored memory, and API contracts are outside the
redesign. Visual verification may use isolated synthetic API fixtures; that is
not a substitute for testing model inference.
