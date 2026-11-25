from sqlmodel import select

import app.services.applications as application_service
import app.services.listings as listing_service
from app.models.application import Application
from app.models.listing import Listing


def test_apply_requires_dcit(monkeypatch, test_session):
    monkeypatch.setattr(application_service, "engine", test_session.bind)
    monkeypatch.setattr(
        application_service,
        "get_user",
        lambda graduate_id: {"id": graduate_id, "role": "graduate", "programme": "OTHER"},
    )

    result = application_service.apply(1, 1, "letter")

    assert result["ok"] is False
    assert result["status_code"] == 403


def test_external_apply_creates_no_application(monkeypatch, test_session):
    listing = Listing(
        employer_id=10,
        title="External",
        company="Company",
        description="Role",
        apply_mode="external",
        external_url="https://example.com/apply",
        deadline="2099-12-31",
        status="published",
    )
    test_session.add(listing)
    test_session.commit()

    monkeypatch.setattr(application_service, "engine", test_session.bind)
    monkeypatch.setattr(
        application_service,
        "get_user",
        lambda graduate_id: {
            "id": graduate_id,
            "role": "graduate",
            "programme": "DCIT",
            "resume_text": "resume",
        },
    )

    result = application_service.apply(1, listing.id, "letter")

    assert result["ok"] is True
    assert result["external_url"] == "https://example.com/apply"
    assert test_session.exec(select(Application)).all() == []


def test_apply_refuses_active_and_allows_reapplication(monkeypatch, test_session):
    listing = Listing(
        employer_id=10,
        title="Internal",
        company="Company",
        description="Role",
        apply_mode="collect",
        external_url=None,
        deadline="2099-12-31",
        status="published",
    )
    test_session.add(listing)
    test_session.commit()

    active = Application(
        listing_id=listing.id,
        graduate_id=1,
        cover_letter="old",
        resume_text="resume",
        status="submitted",
    )
    test_session.add(active)
    test_session.commit()

    monkeypatch.setattr(application_service, "engine", test_session.bind)
    monkeypatch.setattr(
        application_service,
        "get_user",
        lambda graduate_id: {
            "id": graduate_id,
            "role": "graduate",
            "programme": "DCIT",
            "resume_text": "resume",
        },
    )

    refused = application_service.apply(1, listing.id, "letter")
    assert refused["status_code"] == 409

    active.status = "rejected"
    test_session.add(active)
    test_session.commit()

    allowed = application_service.apply(1, listing.id, "new letter")
    assert allowed["ok"] is True


def test_listing_applicant_privacy(monkeypatch, test_session):
    owned = Listing(
        employer_id=10,
        title="Owned",
        company="Company",
        description="Role",
        apply_mode="collect",
        deadline="2099-12-31",
        status="published",
    )
    test_session.add(owned)
    test_session.commit()

    monkeypatch.setattr(application_service, "engine", test_session.bind)
    monkeypatch.setattr(
        application_service,
        "get_user",
        lambda user_id: (
            {"id": user_id, "role": "employer"}
            if user_id in {10, 11}
            else {"id": user_id, "role": "admin"}
        ),
    )

    assert application_service.listing_applicants(11, owned.id)["status_code"] == 403
    assert application_service.listing_applicants(99, owned.id)["ok"] is True
    assert application_service.export_applicants(11, owned.id)["status_code"] == 403
    assert application_service.export_applicants(99, owned.id)["ok"] is True


def test_subscribe_requires_dcit(monkeypatch, test_session):
    monkeypatch.setattr(listing_service, "engine", test_session.bind)
    monkeypatch.setattr(
        listing_service,
        "get_user",
        lambda graduate_id: {"id": graduate_id, "role": "graduate", "programme": "OTHER"},
    )

    result = listing_service.subscribe(1)

    assert result["ok"] is False
    assert result["status_code"] == 403
