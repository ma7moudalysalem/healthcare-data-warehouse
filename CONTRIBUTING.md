# Contributing

Quick notes for the team. The DEPI graduation cohort is the main audience,
but the project is MIT-licensed so external contributions are welcome.

## Local setup

```bash
git clone https://github.com/ma7moudalysalem/healthcare-data-warehouse.git
cd healthcare-data-warehouse
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install flake8 pytest           # dev tools
```

## Branching and commits

* `main` is the integration branch.
* Feature branches: `feat/<short-topic>`, e.g. `feat/silver-fact-prescription`.
* Bug fixes: `fix/<short-topic>`.
* Commit messages: short imperative subject line, blank line, then body if
  the *why* needs explaining. Lowercase subject is fine.

```
M3: silver fact_encounter handles null end_at

Synthea ongoing encounters arrive with STOP=null. We were dropping them
on the end>=start rule; relax to allow null end_at and only fail when
both are present and out of order.
```

## Running checks

```bash
make lint       # flake8
make test-fast  # pytest, no Spark
make test       # full pytest including Spark transforms
```

Spark tests need Java 17+ on PATH. If you don't have Spark set up
locally, skip that step - CI runs them on every PR.

## Style

* Python: PEP 8 with the project's `setup.cfg` overrides. Column-aligned
  table-style code is intentional - see the `ignore` list in setup.cfg.
* SQL: 4-space indent, lowercase keywords... no, **uppercase keywords**;
  match the existing files.
* Don't introduce new dependencies without a note in the PR description.

## Adding a new analytical query

1. Place it under `sql/queries/NN_<topic>.sql` with the next free number.
2. Reference `dw.*` views/tables, not the OLTP `clinical.*` / `billing.*`.
3. Keep a single comment block at the top describing the audience and
   purpose.
4. `tests/test_sql_files.py` will pick it up automatically.

## Adding a new Silver transform

1. Drop `pipelines/silver/silver_<table>.py` modelled on the existing
   ones. Reuse `silver_common.split_by_rule` and `write_quarantine`.
2. List your DQ rules in the module docstring.
3. Add the table to the run-all driver (`notebooks/silver_run_all.py`).
4. If your DQ rules are non-obvious, add a regression test under
   `tests/test_silver_common.py` (or split off a new test module).

## Reporting issues

Use GitHub Issues with the `bug`, `enhancement` or `question` label. For
data-quality observations from production, file under `data-quality` and
include the run id from `dw.load_audit`.

## Code of conduct

Be kind. We're all learning.
