# Security

XellCell runs inside your coding agent's hooks and executes shell commands you write into task contracts. This page says what it defends against, how, and where it stops.

## Supply chain
- Every tool in `tools/` uses the Python 3.9+ standard library only. There is no `requirements.txt`, no `package.json`, nothing to install.
- Hooks, tools and tests run as `python3 -I` (isolated mode: `PYTHONPATH`, user site-packages and the working directory are not on the import path).

## What the hooks enforce (`tools/brain_hooks.py pre`)
| Gate | Protects against | What it does |
|---|---|---|
| Contract gate | edits before the task is defined | Edit tools and shell commands that write files are refused until the session's `contract.md` has its request and a requirement filled in (fast lane: one command writes both). Writes to the session's own folder, temp folders and `~/.claude` stay free. |
| Scope gate | private notes leaking into unrelated work | `Brain System/self/` is readable only when the session's `scope_class` is `personal` or `cv_official`. Literal paths, normalised paths, globs, symlinks and recursive readers (`grep -r`, `rg`, `find`, `tar` …) aimed at a folder that contains `self/` all count. |
| Evidence gate | rewriting the record | Writes into `raw/` are refused; writing into another session's folder asks the human. |
| ACTION-RISK | irreversible actions | `git push`, publishing, sending messages, `rm` (also behind `xargs`/`-exec`), `find -delete`, `git clean`, installs and system changes ask the human first. |
| PRIVACY-LEAK | personal data in outgoing requests | Network commands and web searches that carry an e-mail address, a phone number, a long ID number or a term from `state/privacy-terms.json` are refused until redacted. |

A gate that crashes is logged to `state/analysis/hook-errors.log` and the other gates still decide. The readiness card shows hook errors from the last 7 days, because a gate that errors lets that call through.

## What the judge does not trust
- The maker's summaries are placed last in the judge brief, labelled as claims; checkpoints and chat never enter the brief.
- Tier-0 checks run before any model; a failed check ends the round without a model call. A check that exits 0 while printing an error is shown as `PASS?`.
- The judge is a different vendor's CLI, run read-only in an empty temporary folder with the brain's hooks switched off (`BRAIN_OFF=1`).
- Its answer is checked by code (`review_verdict()`, `quoted()`): missing verdicts, a `pass` beside an open requirement, a `pass` above a failed blocker and a `pass` resting only on quotes found nowhere in the packet or the artifacts are all downgraded. Code never upgrades a verdict.
- `--record FILE` (a judge run by hand) runs Tier 0 again and applies the same checks; it records which judge it was and marks a judge of the maker's own vendor. It does not verify who produced the file: keep exported packages and answers on trusted storage.

## Your responsibilities
1. **Treat `## Checks` in a contract like a Makefile.** `cmd:` lines run in a shell. Review contracts that come from someone else before judging them.
2. **Keep private data out of git.** The shipped `.gitignore` keeps sessions, queue, reports, indexes, `Brain System/self/`, your projects, history, lessons and runtime state local. Removing those lines publishes them.
3. **The gates are a seatbelt, not a sandbox.** Shell write detection is best effort; a determined agent can work around a hook. Use your agent's own permission system as well.

## Reporting a vulnerability
Open a GitHub security advisory on this repository (Security → Advisories → Report a vulnerability) rather than a public issue. Include the hook or tool, the input that bypasses it, and what happened.
