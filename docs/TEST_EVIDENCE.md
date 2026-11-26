# Test & coverage evidence

Part 4 (tests & coverage), P4: Johnathan Laldeo

## How to reproduce

```powershell
pip install -r requirements.txt          # includes pytest-cov
pytest                                   # runs all tests + prints coverage
pytest --cov-report=html                 # browsable report in docs/coverage/html/
```

Tests run against a throwaway SQLite file in the OS temp folder (set in
`tests/conftest.py`), so they never touch the developer `database.db`.
Each API test re-seeds the database, so tests are independent of order.

## Result (measured on `main` after PRs #1, #2, #3, #5)

- **148 tests: 141 passed, 7 expected failures (xfail)**. The xfails are real
  defects found by these tests and handed to their owners (see below).
  Full list in [`coverage/test-results.txt`](coverage/test-results.txt).
- **Coverage (line + branch)**: full report in [`coverage/coverage.txt`](coverage/coverage.txt).

| Module | Starter | Now |
|---|---|---|
| `routers/board.py` | 60% | 96% |
| `services/applications.py` | 16% | 85% |
| `services/listings.py` | 27% | 95% |
| `services/application_states.py` | 97% | 97% |
| `services/application_history.py` | (new) | 93% |
| `models/application.py` | 100% | 91% |
| `models/status_change.py` | (new) | 100% |

Project total is 67%. The rest is mostly FastStart base code (server config
panel, SSR pages). Course tooling (`report_pdf.py`, `transcript_export.py`,
`usecase_diagram.py`, `skill_integrity.py`, `cli.py`) is excluded in `.coveragerc`.

## Test suites

| File | Owner | Level | Focus |
|---|---|---|---|
| `tests/test_acceptance.py` | P4 (this PR) | HTTP API | One class per acceptance criterion AC1–AC16 |
| `tests/test_states.py` | #1 | Unit | Every legal/illegal State transition |
| `tests/test_models.py` | #2 | Unit | `Application.perform()` and `StatusChange` |
| `tests/test_apply_privacy.py` | #2 | Service | DCIT eligibility, external apply, re-apply, applicant privacy |
| `tests/test_listings.py` | #3 | Service/API | Approval workflow, `is_open`, publish-notifies |
| `tests/test_transitions.py` | #5 | API | Owner-only transitions, `StatusChange` + `Notification` persisted, history |
| `tests/test_unit.py`, `test_integration.py`, `test_scenario.py` | Starter | Mixed | Auth, password hashing, smoke |

## Acceptance criteria → tests

| # | Criterion | `test_acceptance.py` class | Also covered by |
|---|---|---|---|
| 1 | Graduates browse, subscribe, apply | `TestAC1GraduateRole` | |
| 2 | Employers submit listings, review own applicants | `TestAC2EmployerRole` | `test_listings.py` |
| 3 | Admins review/publish, notify, export | `TestAC3AdminRole` | `test_listings.py` |
| 4 | Pending hidden until published | `TestAC4PendingNotVisible` | `test_listings.py` |
| 5 | Apply mode external-link / collect | `TestAC5ApplyMode` | |
| 6 | Hidden after deadline | `TestAC6Deadline` | `test_listings.py` (`is_open`) |
| 7 | Publishing notifies subscribers | `TestAC7PublishNotifies` | `test_listings.py` |
| 8 | Only DCIT graduates subscribe/apply | `TestAC8Eligibility` | `test_apply_privacy.py` |
| 9 | Apply captures cover letter + resume, starts `submitted` | `TestAC9OnPlatformApply` | |
| 10 | Only legal lifecycle transitions | `TestAC10Lifecycle` | `test_states.py`, `test_models.py`, `test_transitions.py` |
| 11 | One consistent status | `TestAC11ConsistentStatus` | `test_models.py` |
| 12 | Only listing employer advances lifecycle | `TestAC12OnlyListingEmployerTransitions` | `test_transitions.py` |
| 13 | External apply not recorded in-app | `TestAC13ExternalApply` | `test_apply_privacy.py` |
| 14 | Passwords hashed; never returned | `TestAC14Passwords`, `TestUnauthorizedResponses` | `test_unit.py`, `test_integration.py` |
| 15 | Employers can't see other listings' applicants | `TestAC15EmployerDataIsolation` | `test_apply_privacy.py`, `test_transitions.py` |
| 16 | Admin export of applicant packages | `TestAC16AdminExport` | |

## Defect fixes, credited

Fixed by teammates and **verified** by the acceptance tests:

| Defect in starter | Fixed in |
|---|---|
| Lifecycle was a status string + four boolean flags | #1 (State classes), #2 (flags removed, `perform()`, `StatusChange`) |
| Graduate view read flag-derived status | #2 |
| No DCIT eligibility check on subscribe/apply | #2 |
| External-link listings created an application row | #2 |
| Any employer could read any listing's applicants (IDOR) | #2 |
| Listings published immediately, skipping admin review | #3 |
| Pending and expired listings visible to graduates | #3 (`is_open`) |
| Publishing did not notify subscribers | #3 |
| Illegal jumps, admin/any employer could transition | #5 |
| No audit trail or applicant notice on transition | #5 (`StatusChange` + `Notification`) |

Fixed in **this PR** (P4):

| Defect | AC | Fix |
|---|---|---|
| Global 401 handler served HTML with **200 OK**, so a failed API login looked successful | 14 | `app/main.py`: `/api/*` gets JSON 401; HTML page keeps status 401 |

## Open defects found by these tests (xfail, for owners)

Marked `xfail(strict=True)` in `tests/test_acceptance.py`. When an owner fixes
one, its test XPASSes and pytest fails, so the marker gets removed.

| Defect | AC | Owner | Test(s) |
|---|---|---|---|
| `board.py` subscribe/apply raise HTTP 400 instead of the service `status_code` (non-DCIT gets 400 not 403; duplicate gets 400 not 409) | 1, 8, 9 | P2 | `test_non_graduates_cannot_apply_or_subscribe`, `test_non_dcit_graduate_cannot_subscribe`, `test_non_dcit_graduate_cannot_apply`, `test_duplicate_application_rejected` |
| Empty cover letter accepted | 9 | P2 | `test_cover_letter_required` |
| Non-ISO deadline accepted; listing then never visible | 5, 6 | P1 | `test_rejects_bad_deadline` |
| `notify_subscribers` notifies about pending listings | 4, 7 | P1 | `test_cannot_notify_about_unpublished_listing` |

## Other notes

- `GET /api/users` (FastStart base) lists every user's email without login.
- `my_applications` adds `display_status = "closed"` for submitted/reviewed
  applications on closed listings. A deliberate team choice, but it is a second
  label beside `status` (AC11); worth defending in the demo.
