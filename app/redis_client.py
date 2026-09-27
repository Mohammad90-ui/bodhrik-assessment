"""
Redis's one real job in this system: it's the queue backing the review
summarization endpoint. POST /reviews/{id}/summarize pushes a review_id
onto this list; worker.py is a separate process that pops from it and
writes the (stubbed) summary back to Postgres. No real LLM call — just
proving the queue plumbing works end to end, as the brief allows.

get_summary_queue is a FastAPI dependency wrapping the plain
enqueue_review_summary function purely so tests can override it with a
no-op, instead of needing a real Redis connection to run the test suite.
"""

import os

import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
QUEUE_KEY = "review_summary_queue"

_redis_conn: "redis.Redis | None" = None


def get_redis() -> redis.Redis:
    global _redis_conn
    if _redis_conn is None:
        _redis_conn = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_conn


def enqueue_review_summary(review_id: str) -> None:
    get_redis().rpush(QUEUE_KEY, review_id)


def get_summary_queue():
    """FastAPI dependency: returns the callable used to enqueue a job."""
    return enqueue_review_summary
