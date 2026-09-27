from datetime import timedelta

import jwt

from app.auth import ALGORITHM, SECRET_KEY
from app.time_utils import utcnow


def test_malformed_sub_in_token_returns_401_not_500(client):
    """
    Regression test for a real bug: a validly-signed token whose `sub`
    claim isn't a parseable UUID used to crash get_current_user with an
    unhandled ValueError (-> 500) instead of a clean 401.
    """
    bad_payload = {
        "sub": "this-is-not-a-uuid",
        "role": "customer",
        "exp": utcnow() + timedelta(minutes=5),
    }
    bad_token = jwt.encode(bad_payload, SECRET_KEY, algorithm=ALGORITHM)

    resp = client.get("/bookings", headers={"Authorization": f"Bearer {bad_token}"})
    assert resp.status_code == 401


def test_token_with_no_sub_claim_returns_401(client):
    bad_payload = {"role": "customer", "exp": utcnow() + timedelta(minutes=5)}
    bad_token = jwt.encode(bad_payload, SECRET_KEY, algorithm=ALGORITHM)

    resp = client.get("/bookings", headers={"Authorization": f"Bearer {bad_token}"})
    assert resp.status_code == 401


def test_garbage_token_returns_401(client):
    resp = client.get("/bookings", headers={"Authorization": "Bearer not.a.jwt.at.all"})
    assert resp.status_code == 401


def test_non_string_sub_in_token_returns_401_not_500(client):
    """
    Regression test: a `sub` claim that's valid JSON but not a string at
    all (e.g. a bare number) raised an unhandled AttributeError inside
    uuid.UUID(), not the ValueError the previous fix caught — same bug
    class, different exception type.
    """
    bad_payload = {"sub": 12345, "role": "customer", "exp": utcnow() + timedelta(minutes=5)}
    bad_token = jwt.encode(bad_payload, SECRET_KEY, algorithm=ALGORITHM)

    resp = client.get("/bookings", headers={"Authorization": f"Bearer {bad_token}"})
    assert resp.status_code == 401


def test_cannot_self_register_as_admin(client):
    """Regression test: /auth/register used to accept role=admin from anyone."""
    resp = client.post(
        "/auth/register",
        json={"email": "wannabe-admin@example.com", "password": "password123", "role": "admin"},
    )
    assert resp.status_code == 403


def test_can_still_self_register_as_customer_or_provider(client):
    resp = client.post(
        "/auth/register",
        json={"email": "realcustomer@example.com", "password": "password123", "role": "customer"},
    )
    assert resp.status_code == 201
