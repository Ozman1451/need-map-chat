---
name: verify
description: Run the full project check (tests, lint, build, pipeline smoke run) and fix failures. Use after finishing any phase or before committing.
---

1. Confirm `echo $CONDA_DEFAULT_ENV` prints `ccc`; if not, stop and tell the user to activate it.
2. Run `make verify`.
3. If anything fails, fix the root cause (not the test) and re-run until it passes. Summarise errors; don't paste long logs.
4. Only if this phase changed the frontend: run `npm run shot` in `frontend/`, look at at most 2 screenshots in `shots/`, fix obvious visual problems once.
5. Report in ≤5 lines: what passed, what you fixed, anything open.
