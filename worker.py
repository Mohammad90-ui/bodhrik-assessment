"""
Standalone worker process: pulls review IDs off the Redis queue and
writes a summary back to Postgres. Deliberately a stub — the brief says
no real LLM call is needed, just proof the queue plumbing works.

Run it as its own container/process: `python worker.py`
(docker-compose runs this in a separate `worker` service, sharing the
same image as the API but with a different command.)
"""

import time
import uuid

import redis

from app.database import SessionLocal
from app.models import Review, SummaryStatus
from app.redis_client import QUEUE_KEY, get_redis

RETRY_DELAY_SECONDS = 5


def summarize_stub(text: str | None) -> str:
    """Not a real LLM call — truncates the review text to prove the pipeline works."""
    if not text:
        return "No written feedback was provided."
    words = text.split()
    snippet = " ".join(words[:15])
    return f"Summary: {snippet}{'...' if len(words) > 15 else ''}"


def process_job(review_id_str: str) -> None:
    db = SessionLocal()
    try:
        review = db.query(Review).filter(Review.id == uuid.UUID(review_id_str)).first()
        if review is None:
            print(f"Review {review_id_str} not found, skipping")
            return
        review.summary = summarize_stub(review.text)
        review.summary_status = SummaryStatus.done
        db.commit()
        print(f"Summarized review {review_id_str}")
    finally:
        db.close()


def _process_one(conn: redis.Redis) -> None:
    """
    Pops and handles exactly one job. Split out from run() specifically so
    it's unit-testable without a real infinite loop: a bad job, a bad
    review ID, or a transient Redis error must skip/retry that ONE job,
    never bring down the whole worker process.
    """
    try:
        _, review_id_str = conn.brpop(QUEUE_KEY)
    except redis.exceptions.RedisError as exc:
        print(f"Redis error while waiting for a job, retrying in {RETRY_DELAY_SECONDS}s: {exc}")
        time.sleep(RETRY_DELAY_SECONDS)
        return

    try:
        process_job(review_id_str)
    except Exception as exc:
        # A single bad job (malformed ID, DB hiccup, whatever) must not
        # kill the process — log it and keep consuming the queue. This is
        # still "at most once" delivery (BRPOP already removed the item
        # before we got here) — a real production fix would move to
        # BRPOPLPUSH/Streams with an acknowledgement step, noted in
        # WRITTEN_NOTE.md as a known gap.
        print(f"Failed to process job for review {review_id_str}: {exc}")


def run() -> None:
    conn = get_redis()
    print("Worker started, waiting for review summarization jobs...")
    while True:
        _process_one(conn)


if __name__ == "__main__":
    run()
