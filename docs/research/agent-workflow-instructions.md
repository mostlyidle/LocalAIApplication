# Where to put coding-agent workflow instructions

## Recommendation

Put a short implementation and verification loop in the repository-root `AGENTS.md`. This is a durable, repo-wide working agreement that should apply to future feature work across the project. Keep it specific to this codebase and concise; link to a separate guide only if the procedure grows beyond a few actionable steps.

Use a skill when the workflow should be reusable across repositories, has a specific trigger, or needs supporting scripts and reference material. A skill is modular workflow guidance, while `AGENTS.md` is persistent project guidance. For this repository, the general feature loop belongs in `AGENTS.md`; a dedicated skill would add unnecessary indirection today.

## Evidence

- The [AGENTS.md site](https://agents.md/) describes the format as a predictable place for project context and agent instructions. It recommends a root file for general project guidance and nested files for subprojects; its FAQ says there are no required fields and that listed testing commands are attempted by agents.
- [Codex's AGENTS.md guide](https://learn.chatgpt.com/docs/agent-configuration/agents-md) says Codex loads project instructions from the repository root down to the working directory. Root rules therefore establish project-wide defaults, while closer files can specialize them. It also recommends concise review rules and putting repository-wide checks at the root.
- OpenAI's [skills guide](https://developers.openai.com/api/docs/guides/tools-skills) describes skills as modular instructions for reusable processes, conventions, and multi-step workflows, with supporting files where needed. OpenAI's [Codex workflow guidance](https://developers.openai.com/cookbook/examples/codex/iterating-development-workflows-with-codex) distinguishes `AGENTS.md` as durable repository instructions and working agreements from skills used to make workflows reusable.
- OpenAI's [guidance on keeping `AGENTS.md` current](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra) cautions that it applies whenever an agent works in the repository, so instructions should stay useful and concise instead of requiring heavyweight procedures on every task.

## Practical boundary

The root instructions should tell an agent to define observable success, reproduce and diagnose failures where applicable, make the smallest complete change, run relevant verification, review the diff against the request, fix findings, and repeat the affected checks. The depth of each step should scale with the change: a one-line edit does not need a full investigation, while a model-backed feature failure may need controlled hypothesis testing and an end-to-end check. Record exact checks and results; do not imply a check passed if it was not run.
