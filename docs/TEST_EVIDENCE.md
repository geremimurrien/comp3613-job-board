# Test & coverage evidence

Branch: `feature/2-tests-coverage-evidence`

## How to reproduce

```powershell
pip install -r requirements.txt pytest-cov
pytest                                   # runs all tests + prints coverage
pytest --cov-report=html                 # browsable report in docs/coverage/html/
```

Tests run against a throwaway SQLite file in the OS temp folder (set in
`tests/conftest.py`), so they never touch the developer `database.db`.
Each API test re-seeds the database, so tests are independent and order-free.

## Result

- **111 tests, all passing** — full list in [`coverage/test-results.txt`](coverage/test-results.txt)
- **Coverage (line + branch)** — full report in [`coverage/coverage.txt`](coverage/coverage.txt)

| Module (job-board domain) | Before | After |
|---|---|---|
| `services/application_states.py` | 97% | 98% |
| `services/applications.py` | 16% | 95% |
| `services/listings.py` | 27% | 89% |
| `routers/board.py` | 60% | 98% |
| `services/board_auth.py` | 76% | 94% |
| `services/lifecycle.py` (flag-based tracker) | 8% | removed |

Project total is 65%. The remainder is mostly FastStart base code (server config
panel, SSR templates/CLI). Course tooling (`report_pdf.py`, `transcript_export.py`,
`usecase_diagram.py`, `skill_integrity.py`, `cli.py`) is excluded in `.coveragerc`
because it is not job-board behaviour.

## Acceptance criteria → tests

All in `tests/test_acceptance.py` unless noted. Test classes are named after the criterion.

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
| 10 | Only legal lifecycle transitions | `TestAC10Lifecycle`, `tests/test_states.py` |
| 11 | One consistent status | `TestAC11ConsistentStatus` |
| 12 | Only listing employer advances lifecycle | `TestAC12OnlyListingEmployerTransitions` |
| 13 | External-link apply not recorded in-app | `TestAC13ExternalApply` |
| 14 | Passwords hashed; never returned | `TestAC14Passwords`, `TestUnauthorizedResponses`, `tests/test_unit.py` |
| 15 | Employers can't see other listings' applicants | `TestAC15EmployerDataIsolation` |
| 16 | Admin export of applicant packages | `TestAC16AdminExport` |

## Defects found and fixed

| Defect | Criterion | Fix |
|---|---|---|
| Employer listings published immediately, skipping admin review | 4 | `submit_listing` creates `pending`; only `pending` can be published |
| `/api/jobs` returned pending and expired listings | 4, 6 | Filter to published and `deadline >= today` |
| Publishing did not notify subscribers | 7 | `publish_listing` notifies in the same transaction |
| No DCIT check on subscribe/apply | 8 | `is_eligible_graduate` used by both |
| Could apply to pending/expired listings | 4, 6 | Apply requires listing open to graduates |
| External listings created an application row | 13 | Returns `external_url`, `collected: false`, writes nothing |
| Lifecycle allowed jumps (e.g. submitted → hired), hire after reject, `reopen` left stale flags | 10 | Replaced `lifecycle.py` with the State pattern (`application_states.py`); illegal moves → 409 |
| Status stored as string **and** four flags; graduate view read the flags | 11 | Flag columns removed; `status` is the single source of truth |
| Admins and any employer could transition any application | 12 | Only the employer who owns the listing; others → 403 |
| Any employer could read any listing's applicants (IDOR) | 15 | Ownership check; admin allowed for export |
| Global 401 handler served HTML with **200 OK**, so a failed API login looked successful | 14 | `/api/*` gets JSON 401; HTML page keeps status 401 |
| All service errors surfaced as 400 | — | Services return a `code`; router maps to 403/404/409 |

### Design decision: no `reopen`

`rejected` and `hired` are terminal. Criterion 10 allows terminal → active only
with a defensible reopen rule; we chose none. A rejected candidate re-applies
instead of an employer silently reviving a closed decision, which keeps the
history honest and the state machine small. Adding one later means adding a
`reopen` method to `RejectedState` only.
