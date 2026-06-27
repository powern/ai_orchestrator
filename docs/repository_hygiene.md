# Repository Hygiene and Verification

## Generated Artifacts

The repository must not track generated runtime artifacts. The following are
ignored and guarded in CI:

- `__pycache__/`
- `*.py[cod]`
- `.pytest_cache/`
- runtime databases and logs
- `studio/workspaces/`
- `studio/projects/`
- `studio/logs/`
- local virtual environments and IDE files

The CI workflow includes a repository hygiene step and the pytest suite includes
`tests/test_repository_hygiene.py` to prevent regressions.

## Production Smoke Verification

```bash
cd /opt/ai-agent-lab/ai_orchestrator
source /opt/ai-agent-lab/venv/bin/activate
git pull origin main
pytest -q
systemctl restart ai-studio-scheduler.service
systemctl status ai-studio-scheduler.service --no-pager
```

## Full Developer Verification

```bash
pip install -r requirements-dev.txt
python -m compileall -q -x "studio[/\\]workspaces" agents core studio tests
black --check .
ruff check .
flake8 .
pytest -q
```

`compileall` intentionally excludes `studio/workspaces` for local verification
because workspaces are generated runtime data and may contain broken projects
created during repair tests or production experiments.

## GitHub Actions Verification

Workflow: `Repository Verification`

Job: `Quality Gates`

Triggers:

- push to `main`
- pull request targeting `main`

The workflow installs `requirements-dev.txt`, checks repository hygiene, validates
imports, runs Black, Ruff, Flake8, and runs the full pytest suite.

If GitHub previously could not verify checks, the most likely cause was that the
workflow and local documentation depended on dev tools (`black`, `ruff`,
`flake8`) that were not declared in a dependency file. The workflow now installs
all verification tools explicitly from `requirements-dev.txt` and has clear
push/PR triggers.

## Legacy Local Files

The following names were reported on production as untracked local artifacts.
They are not present in this repository checkout and are not required by the
current Flask scheduler application.

- `control_panel/`: obsolete/local prototype; keep out of Git unless reviewed
  and migrated into tested application code.
- `orchestrator.py`: obsolete/local prototype entrypoint; keep out of Git.
- `orchestrator_tasks.db`: runtime database; keep out of Git.
- `run_orchestrator.sh`: local helper script; keep out of Git unless rewritten
  under `scripts/` with tests/docs.
- `run_studio_dev.sh`: local helper script; keep out of Git unless rewritten
  under `scripts/` with tests/docs.
- `orchestrator.log`: runtime log; keep out of Git.
