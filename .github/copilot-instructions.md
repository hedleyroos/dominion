# Copilot Instructions

Personal coding standards derived from the global template, with Dominion-specific customizations applied.

## What are we doing

This is Dominion, an RBAC system developed in Django. It also provides OIDC. It is fully API driven, and can also be used directly in a Django project.

## Rules of Engagement

- **Address the user as "Daddy"** — in every response, to signal when context window has degraded.
- **Don't run tests after every edit** — only run `tox` when you believe a task is complete, or when you need deterministic confirmation that a refactor hasn't broken anything. Don't run linters or tests after individual file changes mid-task.
- When implementing a plan, start each phase in a new agent to prevent context drift.
- When checking on shell progress, and it looks like a long running task, decrease the check frequency.
- **Ask before guessing** — when intent is genuinely ambiguous and the cost of guessing wrong is high (destructive actions, architectural decisions, public APIs), ask a focused clarifying question. For low-stakes ambiguity, pick the most likely interpretation and proceed.
- **When autopilot is on, do not ask at all, or try to run sudo** unless you have hit a complete dead end. Pick the best interpretation, record the assumption in the plan doc you're working from, and continue; list any deferred questions at the end of the run for review.

## General Principles

- **Prefer explicit over implicit** — avoid magic; name things clearly.
- **Always write tests for new code** — no feature is done without tests. Use pytest via tox.
- **Create plan docs before implementing** — write a markdown plan in `docs/plans/` before starting any non-trivial work. This is **extremely important**, because if our context gets degraded we can start a fresh context and not redo any work.
- **Don't over-split files** — keep code in a single module (e.g. `views.py`, `models.py`) until it genuinely becomes unwieldy. A 400-line `views.py` does not need splitting into `views/cars.py` and `views/manufacturers.py`. Only create new files when there is a clear organisational benefit.

## Key Documentation

- **`docs/architecture.md`** — the primary project reference. Read this for architecture, modelling decisions, migration status, and what remains to be ported. Consult it before planning new features.
- **`docs/plans/`** — historical migration plans from earlier phases (admin, code, data migration) and any active plans. Treat older plans as context for past decisions, not as active requirements unless explicitly referenced.

## Research

- If you do not already have a library's code loaded in your context, then consult the library's online documentation first.
- If the online documentation is insufficient, then only read the library's source code.

## Python

- **Follow PEP 8** — standard formatting and naming conventions.
- **Use type hints** — annotate function parameters and return types, but **not** for local variables.
- **No code in f-strings** — declare a local variable first, then reference it in the f-string.

  ```python
  # Bad
  print(f"Result: {some_dict[key].calculate()}")

  # Good
  result = some_dict[key].calculate()
  print(f"Result: {result}")
  ```

- **Virtual environment** — use the `ve` directory.
- **Imports at the top** — put imports at the top of a module as far as possible. **No relative imports.**
- **No class-only encapsulation** — don't create classes with only `staticmethod`s. Use functions instead; the module itself is the encapsulation.
- **Terse comments** — good Python is self-documenting. If a comment has more than one sentence, end with a full stop. All comments must start with a capital letter. Never put comments on the same line as code. No excessive ASCII delimiters.
- **Fail fast** — assume invariants hold. Don't silently swallow exceptions, and don't use `dict.get(key, default)` for mandatory keys — let a missing key raise `KeyError`.
- **No unnecessary abbreviations** — if a variable name is eight characters or fewer, spell it out fully. For example, use `response` not `resp`, `request` not `req`, `result` not `res`, `message` not `msg`.
- **File permissions** — don't make Python files executable, unless explicitly stated.

## Django

- **Follow Django best practices** — fat models/thin views, use Django's ORM properly, leverage built-in features before reaching for third-party packages.
- **Keep views focused** — each view should do one thing.
- **Use Django's URL naming** — always use `reverse()` or `{% url %}` instead of hardcoded paths.
- **Atomicity** — wrap multi-step writes in `transaction.atomic`.
- **Admin vs management interface** — "admin" means Django admin at `/admin/`, intended for superusers. "Management interface", sometimes called the Project Console, means the interface intended for authenticated end users (e.g. clients' employees).
- Do not set `db_table` explicitly, unless we must interface with an existing production database.

## Testing

- **Test runner:** pytest via tox (`tox` to run all tests). Use multiple cores: append `-- -n <number_of_cores>`.
- **Test structure:** tests live in the top-level `tests/` directory.
- **Use fixtures** — shared fixtures go in `conftest.py`.
- **Parameterize** — use `@pytest.mark.parametrize` for repetitive test cases.
- **Test against both SQLite and Postgres.**

## Project Specific

- **Project context:** Dominion is an RBAC system developed in Django. It also provides OIDC. It is fully API driven.
- Use our local Docker pull through registry on port 5000.
