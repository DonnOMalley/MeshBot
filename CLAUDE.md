# MeshBot — notes for Claude Code

## One repo, two paths

`~/source/MeshBot` is a symlink to `~/source/donnomalley/MeshBot`. They are the
same checkout, not two copies. Edit, commit and run from
`~/source/donnomalley/MeshBot`, and treat a search hit in both paths as one file.

## Coding standards

Follow `.github/copilot-instructions.md`. Copilot reviews every PR against it: typed
locals, explicit return types, named constants instead of inline literals, a single
return statement, Google-style docstrings, regions, and one class per file.

## Every change gets a version

Each change merged into `main` gets its own version bump, even small ones:

- Bump the patch number (v0.13.7 → v0.13.8) unless told otherwise.
- Add a `### vX.Y.Z — YYYY-MM-DD` entry at the top of **Release Notes** in `README.md`.
- Add a `New in vX.Y.Z:` line at the top of the release list in
  `web/templates/about.html`, and move the previous one down as a plain `vX.Y.Z:` line.
- Put the version in the PR title, e.g. `Events agenda: hide past events by default (v0.13.6)`.

## Workflow

- Work on a `feature/...` branch from `main`, then open a PR into `main`.
- Wait for the Copilot review, then fix or answer each comment and resolve its thread.
- Merge with a merge commit, delete the branch locally and on GitHub, and pull `main`.
- Tests: the `.venv` has no pytest, so use the system one with the venv's Python:

  ```bash
  PYTHONPATH=$(python3 -c "import pytest,os;print(os.path.dirname(os.path.dirname(pytest.__file__)))") \
    .venv/bin/python -m pytest -q -p no:cacheprovider
  ```

- Restart the web server after changes with `./reload_web.sh`.
