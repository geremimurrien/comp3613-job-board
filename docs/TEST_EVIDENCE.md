# Test & coverage evidence

Branch: `feature/2-tests-coverage-evidence` · Owner: Johnathan Laldeo

## How to reproduce

```powershell
pip install -r requirements.txt pytest-cov
pytest                                   # runs all tests + prints coverage
pytest --cov-report=html                 # browsable report in docs/coverage/html/
```

Tests run against a throwaway SQLite file in the OS temp folder (set in
`tests/conftest.py`), so they never touch the developer `database.db`.
Each API test re-seeds the database, so tests are independent.

## Result

Measured on this branch **with PR #5 (transitions) merged in**. Until #5 lands
on `main`, the AC10/AC12 transition tests fail because `main`'s transition
endpoint still writes the removed `flag_*` columns.

- **148 tests, all passing**: full list in [`coverage/test-results.txt`](coverage/test-results.txt)
- **Coverage (line + branch)**: full report in [`coverage/coverage.txt`](coverage/coverage.txt)

| Module (job-board domain) | Starter | Now |
|---|---|---|
| `routers/board.py` | 60% | 94% |
| `services/applications.py` | 16% | 85% |
| `services/listings.py` | 27% | 92% |
| `services/application_states.py` | 97% | 97% |

Project total is 66%. The rest is mostly FastStart base code (server config
panel, SSR pages). Course tooling (`report_pdf.py`, `transcript_export.py`,
`usecase_diagram.py`, `skill_integrity.py`, `cli.py`) is excluded in `.coveragerc`.

## Acceptance criteria → tests

API-level tests in `tests/test_acceptance.py`; each class is named after its criterion.
Teammates' unit/service tests (`test_states.py`, `test_models.py`,
`test_apply_privacy.py`, `test_listings.py`, `test_transitions.py`) cover the same
rules closer to the code.

| # | Criterion | Test class |
|---|---|---|
| 1 | Graduates browse, subscribe, apply | `TestAC1GraduateRole` |
| 2 | Employers submit listings, review own applicants | `TestAC2EmployerRole` |
| 3 | Admins review/publish, notify, export | `TestAC3AdminRole` |
| 4 | Pending listings hidden until published | `TestAC4PendingNotVisible` |
| 5 | Apply mode external-link / collect | `TestAC5ApplyMode` |
| 6 | Hidden after deadline | `TestAC6Deadline` |
| 7 | Publishing notifies subscribers automatically | `TestAC7PublishNotifies` |
| 8 | Only DCIT graduates subscribe/apply | `TestAC8Eligibility` |
| 9 | On-platform apply captures cover letter + resume, starts `submitted` | `TestAC9OnPlatformApply` |
| 10 | Only legal lifecycle transitions | `TestAC10Lifecycle` |
| 11 | One consistent status | `TestAC11ConsistentStatus` |
| 12 | Only listing employer advances lifecycle | `TestAC12OnlyListingEmployerTransitions` |
| 13 | External-link apply not recorded in-app | `TestAC13ExternalApply` |
| 14 | Passwords hashed; never returned | `TestAC14Passwords`, `TestUnauthorizedResponses` |
| 15 | Employers can't see other listings' applicants | `TestAC15EmployerDataIsolation` |
| 16 | Admin export of applicant packages | `TestAC16AdminExport` |

## Defects found by these tests and fixed in this PR

| Defect | AC | Fix |
|---|---|---|
| Global 401 handler served HTML with **200 OK**, so a failed API login looked successful | 14 | `app/main.py`: `/api/*` gets JSON 401; HTML page keeps status 401 |
| Subscribe, apply and export endpoints ignored the service's `status_code` (e.g. non-DCIT got 400, not 403) | 8, 12 | `app/routers/board.py` uses `result["status_code"]` |
| Empty cover letter accepted | 9 | `apply()` requires a non-blank cover letter |
| Listing deadline not validated ("next week" accepted, listing then never visible) | 5, 6 | `submit_listing()` requires ISO `YYYY-MM-DD` |
| Admin could "notify" subscribers about a pending listing | 4, 7 | `notify_subscribers()` requires a published listing |

Defects fixed by teammates (PRs #1–#3, #5) are verified by the same tests:
pending-until-published, deadline hiding, auto-notify on publish, DCIT
eligibility, external apply not recorded, State-pattern lifecycle with no
illegal jumps, single `status` column, listing-employer-only transitions and
applicant-data ownership.

## Known gaps (not fixed here)

- `GET /api/users` (FastStart base) lists every user's email without login.
- `my_applications` adds a `display_status` of `closed` for submitted/reviewed
  applications on closed listings. This is a deliberate team choice, but it is a
  second label beside `status` (AC11). Worth defending in the demo.
