# Written Note

## Schema shape and normalization tradeoffs

The schema is four tables: `User` (role: admin/provider/customer),
`TimeSlot` (owned by a provider), `Booking` (a customer claiming a slot),
and `Review` (one per completed booking). The one deliberate denormalization
is storing `provider_id` directly on `Booking`, even though it's derivable
by joining through `TimeSlot`. This costs a small amount of redundancy —
and a theoretical risk of drift if a slot's owner ever changed after
booking, which the domain doesn't allow — in exchange for every RBAC check
on a booking being a single indexed `WHERE provider_id = X`, rather than a
join on every read. Given that access control runs on nearly every
request, I judged that worth it. `Review` is kept as its own table (not
inlined onto `Booking`) since it has its own lifecycle — pending vs.
summarized — that's independent of the booking's own status transitions.

## Extending RBAC

RBAC is split into two layers on purpose: `require_role()` checks *what
kind* of user is calling, before any row is loaded; `verify_booking_access()`
checks *whose* row it actually is, once it's fetched. A fourth role (say,
"support") slots in by adding it to the `UserRole` enum and, if it needs
row-level rules like a provider does, adding one more condition to
`verify_booking_access` — not a rewrite. Nested organisations are a
bigger change: I'd add an `org_id` foreign key to `User`, and
`verify_booking_access` would need an additional org-membership check
(e.g., an org-admin can see any booking within their org, not just their
own). That likely means the ownership check becomes a small policy
table rather than inline booleans once role × org × ownership all apply
at once.

## What's missing for production

- **Migrations**: tables come from `init_db.py`'s `create_all`, not
  Alembic — fine here, but a real schema change needs versioned migrations.
- **Secrets**: `JWT_SECRET` and DB/Redis URLs are plain env variables —
  need a real secrets manager in production.
- **Observability**: no structured logging, tracing, or metrics yet.
- **Rate limiting**: `/auth/login` is unprotected against brute-forcing.
- **Worker delivery guarantee**: the worker now survives a bad job or a
  dropped Redis connection instead of crashing, but it's still
  "at most once" — a crash between popping a job and committing it still
  loses that job silently. A real fix needs `BRPOPLPUSH`/Streams with an
  acknowledgement step.
- **Concurrency — found and fixed**: booking and review creation both
  used check-then-write, with a race window where two simultaneous
  requests could both pass and succeed. Booking creation now uses one
  atomic `UPDATE ... WHERE is_booked = false`; review creation catches the
  DB's `IntegrityError` as a fallback. Both are tested, not load-tested.

Also found and fixed via self-review, each with a regression test:
open self-registration as `admin` (now blocked, see `app/create_admin.py`);
a malformed/non-string JWT `sub` crashing auth with a 500 instead of a
401; and a naive/aware datetime mismatch crashing slot creation. Added a
`DELETE /bookings/{id}` route (aliasing the existing soft-cancel) so the
CRUD verb set is complete without hard-deleting booking history.
