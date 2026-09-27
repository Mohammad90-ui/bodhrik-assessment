from datetime import timedelta

from app.models import UserRole
from app.time_utils import utcnow
from tests.conftest import auth_headers, make_user


def _make_booking(client, db_session, provider_email, customer_email):
    provider = make_user(db_session, UserRole.provider, provider_email)
    customer = make_user(db_session, UserRole.customer, customer_email)
    start = utcnow() + timedelta(days=1)
    end = start + timedelta(hours=1)
    slot_id = client.post(
        "/slots",
        json={"start_time": start.isoformat(), "end_time": end.isoformat()},
        headers=auth_headers(provider),
    ).json()["id"]
    booking = client.post(
        "/bookings", json={"slot_id": slot_id}, headers=auth_headers(customer)
    ).json()
    return provider, customer, booking


def test_provider_cannot_read_another_providers_booking(client, db_session):
    provider_a, customer_a, booking = _make_booking(
        client, db_session, "provA@example.com", "custA@example.com"
    )
    provider_b = make_user(db_session, UserRole.provider, "provB@example.com")

    # The owning provider can read it.
    resp = client.get(f"/bookings/{booking['id']}", headers=auth_headers(provider_a))
    assert resp.status_code == 200

    # A different provider cannot.
    resp = client.get(f"/bookings/{booking['id']}", headers=auth_headers(provider_b))
    assert resp.status_code == 403


def test_customer_can_only_read_own_booking(client, db_session):
    _, customer_a, booking = _make_booking(
        client, db_session, "provC@example.com", "custC@example.com"
    )
    customer_b = make_user(db_session, UserRole.customer, "custD@example.com")

    resp = client.get(f"/bookings/{booking['id']}", headers=auth_headers(customer_b))
    assert resp.status_code == 403

    resp = client.get(f"/bookings/{booking['id']}", headers=auth_headers(customer_a))
    assert resp.status_code == 200


def test_admin_can_read_any_booking(client, db_session):
    _, _, booking = _make_booking(client, db_session, "provE@example.com", "custE@example.com")
    admin = make_user(db_session, UserRole.admin, "admin@example.com")

    resp = client.get(f"/bookings/{booking['id']}", headers=auth_headers(admin))
    assert resp.status_code == 200


def test_list_bookings_is_filtered_by_role(client, db_session):
    provider_a, customer_a, booking_a = _make_booking(
        client, db_session, "provF@example.com", "custF@example.com"
    )
    provider_b, customer_b, booking_b = _make_booking(
        client, db_session, "provG@example.com", "custG@example.com"
    )

    resp = client.get("/bookings", headers=auth_headers(provider_a))
    ids = [b["id"] for b in resp.json()]
    assert booking_a["id"] in ids
    assert booking_b["id"] not in ids


def test_provider_cannot_create_a_booking(client, db_session):
    provider = make_user(db_session, UserRole.provider, "provH@example.com")
    start = utcnow() + timedelta(days=1)
    end = start + timedelta(hours=1)
    slot_id = client.post(
        "/slots",
        json={"start_time": start.isoformat(), "end_time": end.isoformat()},
        headers=auth_headers(provider),
    ).json()["id"]

    # A provider (not a customer) trying to book is a role violation, not ownership.
    resp = client.post("/bookings", json={"slot_id": slot_id}, headers=auth_headers(provider))
    assert resp.status_code == 403
