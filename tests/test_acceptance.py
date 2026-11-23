"""API-level tests mapped to docs/ACCEPTANCE.md.

Each test class is named after the acceptance criterion it evidences (AC1..AC16).
Seed data (app/seed.py):
  users    admin, grad.dcit (DCIT), grad.other (OTHER), employer, employer2
  listings "Junior Software Engineer"  collect,  published, employer
           "QA Intern"                 external, pending,   employer
           "Expired Analyst Role"      collect,  published, employer2, deadline 2020
  grad.dcit is subscribed.
"""

from datetime import date, timedelta

import pytest
from sqlmodel import select

from app.models.application import Application
from app.models.listing import Listing
from app.models.notification import Notification

API = "/api"


# --------------------------------------------------------------------------- helpers


def listing_id(db, title):
    return db.exec(select(Listing).where(Listing.title == title)).one().id


def job_ids(client):
    r = client.get(f"{API}/jobs")
    assert r.status_code == 200
    return {j["id"] for j in r.json()["jobs"]}


def submit(client, employer_id, **overrides):
    body = {
        "title": "Backend Developer",
        "company": "Acme Soft",
        "description": "Python services.",
        "apply_mode": "collect",
        "deadline": "2099-01-31",
        "actor_id": employer_id,
    }
    body.update(overrides)
    return client.post(f"{API}/employer/listings", json=body)


def publish(client, admin_id, lid):
    return client.post(f"{API}/admin/listings/{lid}/publish", json={"actor_id": admin_id})


def apply(client, grad_id, lid, cover="I am keen.", resume="Python, SQL."):
    return client.post(
        f"{API}/graduates/applications",
        json={
            "listing_id": lid,
            "cover_letter": cover,
            "resume_text": resume,
            "actor_id": grad_id,
        },
    )


def transition(client, actor_id, app_id, action):
    return client.post(
        f"{API}/applications/{app_id}/transition",
        json={"action": action, "actor_id": actor_id},
    )


@pytest.fixture
def junior(db, client):
    return listing_id(db, "Junior Software Engineer")


@pytest.fixture
def application_id(client, users, junior):
    r = apply(client, users["grad.dcit"], junior)
    assert r.status_code == 200, r.text
    return r.json()["application_id"]


# ------------------------------------------------------------------------ AC1-AC3 roles


class TestAC1GraduateRole:
    def test_graduate_can_browse_subscribe_and_apply(self, client, users, junior):
        grad = users["grad.dcit"]
        assert junior in job_ids(client)
        assert client.post(f"{API}/graduates/subscribe", json={"actor_id": grad}).status_code == 200
        assert apply(client, grad, junior).status_code == 200

    def test_non_graduates_cannot_apply_or_subscribe(self, client, users, junior):
        for name in ("admin", "employer"):
            assert apply(client, users[name], junior).status_code == 403
            r = client.post(f"{API}/graduates/subscribe", json={"actor_id": users[name]})
            assert r.status_code == 403


class TestAC2EmployerRole:
    def test_employer_can_submit_listing(self, client, users):
        r = submit(client, users["employer"])
        assert r.status_code == 200
        assert r.json()["listing_id"]

    def test_graduate_and_admin_cannot_submit_listing(self, client, users):
        assert submit(client, users["grad.dcit"]).status_code == 403
        assert submit(client, users["admin"]).status_code == 403

    def test_employer_reviews_applicants_for_own_listing(
        self, client, users, junior, application_id
    ):
        r = client.get(
            f"{API}/listings/{junior}/applicants",
            params={"actor_id": users["employer"]},
        )
        assert r.status_code == 200
        assert [a["id"] for a in r.json()["applicants"]] == [application_id]


class TestAC3AdminRole:
    def test_admin_sees_pending_publishes_and_exports(
        self, client, users, db, junior, application_id
    ):
        admin = users["admin"]
        r = client.get(f"{API}/admin/listings/pending", params={"actor_id": admin})
        assert r.status_code == 200
        pending = [l["id"] for l in r.json()["listings"]]
        assert listing_id(db, "QA Intern") in pending

        assert publish(client, admin, listing_id(db, "QA Intern")).status_code == 200

        r = client.get(f"{API}/admin/listings/{junior}/export", params={"actor_id": admin})
        assert r.status_code == 200
        assert [a["id"] for a in r.json()["package"]] == [application_id]

    def test_non_admins_cannot_use_admin_endpoints(self, client, users, db, junior):
        qa = listing_id(db, "QA Intern")
        for name in ("employer", "grad.dcit"):
            uid = users[name]
            assert client.get(f"{API}/admin/listings/pending", params={"actor_id": uid}).status_code == 403
            assert publish(client, uid, qa).status_code == 403
            assert client.get(f"{API}/admin/listings/{junior}/export", params={"actor_id": uid}).status_code == 403
            r = client.post(f"{API}/admin/listings/{junior}/notify", json={"actor_id": uid})
            assert r.status_code == 403


# --------------------------------------------------------------------- AC4-AC7 listings


class TestAC4PendingNotVisible:
    def test_new_listing_is_pending_and_hidden_until_published(self, client, users):
        r = submit(client, users["employer"])
        lid = r.json()["listing_id"]
        assert r.json()["status"] == "pending"
        assert lid not in job_ids(client)

        assert publish(client, users["admin"], lid).status_code == 200
        assert lid in job_ids(client)

    def test_seeded_pending_listing_is_hidden(self, client, db):
        assert listing_id(db, "QA Intern") not in job_ids(client)

    def test_cannot_apply_to_pending_listing(self, client, users):
        lid = submit(client, users["employer"]).json()["listing_id"]
        assert apply(client, users["grad.dcit"], lid).status_code == 404

    def test_cannot_publish_twice(self, client, users, junior):
        assert publish(client, users["admin"], junior).status_code == 409


class TestAC5ApplyMode:
    def test_rejects_unknown_apply_mode(self, client, users):
        assert submit(client, users["employer"], apply_mode="email").status_code == 400

    def test_external_requires_url(self, client, users):
        assert submit(client, users["employer"], apply_mode="external").status_code == 400

    def test_both_modes_accepted_and_stored(self, client, users, db):
        e = users["employer"]
        collect = submit(client, e).json()["listing_id"]
        external = submit(
            client, e, apply_mode="external", external_url="https://example.com/x"
        ).json()["listing_id"]
        assert db.get(Listing, collect).apply_mode == "collect"
        assert db.get(Listing, external).apply_mode == "external"
        assert db.get(Listing, external).external_url == "https://example.com/x"

    def test_rejects_bad_deadline(self, client, users):
        assert submit(client, users["employer"], deadline="next week").status_code == 400


class TestAC6Deadline:
    def test_expired_listing_hidden(self, client, db):
        assert listing_id(db, "Expired Analyst Role") not in job_ids(client)

    def test_cannot_apply_after_deadline(self, client, users, db):
        lid = listing_id(db, "Expired Analyst Role")
        assert apply(client, users["grad.dcit"], lid).status_code == 404

    def test_deadline_day_is_still_open_and_day_after_is_closed(self, client, users):
        today = date.today()
        e, admin = users["employer"], users["admin"]
        today_id = submit(client, e, deadline=today.isoformat()).json()["listing_id"]
        past_id = submit(
            client, e, deadline=(today - timedelta(days=1)).isoformat()
        ).json()["listing_id"]
        publish(client, admin, today_id)
        publish(client, admin, past_id)

        visible = job_ids(client)
        assert today_id in visible
        assert past_id not in visible


class TestAC7PublishNotifies:
    def test_publishing_notifies_subscribers_automatically(self, client, users, db):
        lid = submit(client, users["employer"], title="Data Engineer").json()["listing_id"]
        r = publish(client, users["admin"], lid)
        assert r.status_code == 200
        assert r.json()["notified"] is True
        assert r.json()["count"] == 1

        notes = db.exec(
            select(Notification).where(Notification.user_id == users["grad.dcit"])
        ).all()
        assert any("Data Engineer" in n.message for n in notes)

    def test_ineligible_users_are_not_notified(self, client, users, db):
        lid = submit(client, users["employer"]).json()["listing_id"]
        publish(client, users["admin"], lid)
        notes = db.exec(
            select(Notification).where(Notification.user_id == users["grad.other"])
        ).all()
        assert notes == []

    def test_cannot_notify_about_unpublished_listing(self, client, users, db):
        qa = listing_id(db, "QA Intern")
        r = client.post(f"{API}/admin/listings/{qa}/notify", json={"actor_id": users["admin"]})
        assert r.status_code == 409


# ------------------------------------------------------------ AC8-AC13 applications


class TestAC8Eligibility:
    def test_non_dcit_graduate_cannot_subscribe(self, client, users):
        r = client.post(f"{API}/graduates/subscribe", json={"actor_id": users["grad.other"]})
        assert r.status_code == 403

    def test_non_dcit_graduate_cannot_apply(self, client, users, junior, db):
        assert apply(client, users["grad.other"], junior).status_code == 403
        assert db.exec(select(Application)).all() == []

    def test_subscribe_is_idempotent(self, client, users):
        grad = users["grad.dcit"]
        for _ in range(2):
            assert client.post(f"{API}/graduates/subscribe", json={"actor_id": grad}).status_code == 200


class TestAC9OnPlatformApply:
    def test_captures_cover_letter_resume_and_starts_submitted(
        self, client, users, junior, db
    ):
        r = apply(client, users["grad.dcit"], junior, cover="Hire me", resume="CV text")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "submitted"
        assert body["collected"] is True

        row = db.get(Application, body["application_id"])
        assert (row.cover_letter, row.resume_text, row.status) == (
            "Hire me",
            "CV text",
            "submitted",
        )

    def test_falls_back_to_profile_resume(self, client, users, junior, db):
        r = apply(client, users["grad.dcit"], junior, resume=None)
        row = db.get(Application, r.json()["application_id"])
        assert row.resume_text.startswith("DCIT graduate resume")

    def test_cover_letter_required(self, client, users, junior):
        assert apply(client, users["grad.dcit"], junior, cover="   ").status_code == 400

    def test_duplicate_application_rejected(self, client, users, junior, application_id):
        assert apply(client, users["grad.dcit"], junior).status_code == 409


LEGAL_PATH = ["mark_reviewed", "shortlist"]


class TestAC10Lifecycle:
    @pytest.mark.parametrize("final", ["hire", "reject"])
    def test_full_legal_path(self, client, users, application_id, final):
        e = users["employer"]
        expected = ["reviewed", "shortlisted", "hired" if final == "hire" else "rejected"]
        for action, status in zip(LEGAL_PATH + [final], expected):
            r = transition(client, e, application_id, action)
            assert r.status_code == 200, r.text
            assert r.json()["application"]["status"] == status

    @pytest.mark.parametrize("action", ["shortlist", "hire", "reject"])
    def test_no_jumps_from_submitted(self, client, users, application_id, db, action):
        r = transition(client, users["employer"], application_id, action)
        assert r.status_code == 409
        db.expire_all()
        assert db.get(Application, application_id).status == "submitted"

    @pytest.mark.parametrize("final", ["hire", "reject"])
    @pytest.mark.parametrize("action", ["mark_reviewed", "shortlist", "hire", "reject"])
    def test_terminal_states_are_final(self, client, users, application_id, final, action):
        e = users["employer"]
        for step in LEGAL_PATH + [final]:
            transition(client, e, application_id, step)
        assert transition(client, e, application_id, action).status_code == 409

    def test_reopen_is_not_supported(self, client, users, application_id):
        e = users["employer"]
        for step in LEGAL_PATH + ["reject"]:
            transition(client, e, application_id, step)
        assert transition(client, e, application_id, "reopen").status_code == 400

    def test_rejected_graduate_may_apply_again_as_new_application(
        self, client, users, junior, application_id
    ):
        for step in LEGAL_PATH + ["reject"]:
            transition(client, users["employer"], application_id, step)
        r = apply(client, users["grad.dcit"], junior)
        assert r.status_code == 200
        assert r.json()["application_id"] != application_id
        assert r.json()["status"] == "submitted"

    def test_unknown_action_rejected(self, client, users, application_id):
        assert transition(client, users["employer"], application_id, "promote").status_code == 400

    def test_missing_application(self, client, users):
        assert transition(client, users["employer"], 9999, "mark_reviewed").status_code == 404


class TestAC11ConsistentStatus:
    def test_graduate_view_matches_stored_status(self, client, users, application_id, db):
        e, grad = users["employer"], users["grad.dcit"]
        for action in LEGAL_PATH + ["reject"]:
            transition(client, e, application_id, action)
            r = client.get(f"{API}/graduates/applications", params={"actor_id": grad})
            (mine,) = r.json()["applications"]
            db.expire_all()
            assert mine["status"] == db.get(Application, application_id).status

    def test_status_is_the_only_lifecycle_field(self, client, users, application_id):
        r = client.get(f"{API}/graduates/applications", params={"actor_id": users["grad.dcit"]})
        (mine,) = r.json()["applications"]
        assert not [k for k in mine if k.startswith("flag_")]


class TestAC12OnlyListingEmployerTransitions:
    @pytest.mark.parametrize("who", ["admin", "employer2", "grad.dcit", "grad.other"])
    def test_others_cannot_transition(self, client, users, application_id, db, who):
        r = transition(client, users[who], application_id, "mark_reviewed")
        assert r.status_code == 403
        db.expire_all()
        assert db.get(Application, application_id).status == "submitted"

    def test_unknown_actor_cannot_transition(self, client, application_id):
        assert transition(client, 9999, application_id, "mark_reviewed").status_code == 403


class TestAC13ExternalApply:
    def test_external_listing_redirects_and_records_nothing(self, client, users, db):
        qa = listing_id(db, "QA Intern")
        assert publish(client, users["admin"], qa).status_code == 200

        r = apply(client, users["grad.dcit"], qa)
        assert r.status_code == 200
        body = r.json()
        assert body["collected"] is False
        assert body["external_url"] == "https://example.com/apply/qa"
        assert "application_id" not in body
        assert db.exec(select(Application).where(Application.listing_id == qa)).all() == []


# ---------------------------------------------------------------- AC14-AC16 trust


class TestAC14Passwords:
    def test_passwords_hashed_at_rest(self, users, db):
        from app.models.user import User

        admin = db.get(User, users["admin"])
        assert admin.password != "admin-dev"
        assert admin.password.startswith("$")

    @pytest.mark.parametrize(
        ("email", "password"),
        [
            ("admin@example.com", "admin-dev"),
            ("grad.dcit@example.com", "grad-dev"),
            ("employer@example.com", "employer-dev"),
        ],
    )
    def test_login_response_has_no_password_material(self, client, email, password):
        r = client.post(f"{API}/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200
        assert "password" not in r.text.lower()
        assert "$2" not in r.text

    def test_wrong_password_rejected(self, client):
        r = client.post(f"{API}/auth/login", json={"email": "admin@example.com", "password": "x"})
        assert r.status_code == 401


class TestAC15EmployerDataIsolation:
    def test_other_employer_cannot_view_applicants(self, client, users, junior, application_id):
        r = client.get(f"{API}/listings/{junior}/applicants", params={"actor_id": users["employer2"]})
        assert r.status_code == 403
        assert "applicants" not in r.json()

    @pytest.mark.parametrize("who", ["grad.dcit", "grad.other"])
    def test_graduates_cannot_view_applicants(self, client, users, junior, application_id, who):
        r = client.get(f"{API}/listings/{junior}/applicants", params={"actor_id": users[who]})
        assert r.status_code == 403

    def test_missing_listing(self, client, users):
        r = client.get(f"{API}/listings/9999/applicants", params={"actor_id": users["admin"]})
        assert r.status_code == 404


class TestAC16AdminExport:
    def test_export_contains_application_package(self, client, users, junior, application_id):
        r = client.get(f"{API}/admin/listings/{junior}/export", params={"actor_id": users["admin"]})
        assert r.status_code == 200
        (pkg,) = r.json()["package"]
        assert pkg["cover_letter"] and pkg["resume_text"]
        assert "password" not in r.text.lower()


class TestUnauthorizedResponses:
    """Regression: the global 401 handler used to answer with HTML + 200 OK,
    so a failed API login looked like a success to API clients."""

    def test_api_401_is_json(self, client):
        r = client.post(f"{API}/auth/login", json={"email": "nobody@example.com", "password": "x"})
        assert r.status_code == 401
        assert r.headers["content-type"].startswith("application/json")
        assert r.json()["detail"] == "invalid credentials"

    def test_html_401_keeps_status(self, client):
        r = client.get("/admin", follow_redirects=False)
        assert r.status_code == 401
        assert r.headers["content-type"].startswith("text/html")
