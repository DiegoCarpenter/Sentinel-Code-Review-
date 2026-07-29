"""Toy Flask-style API layer for the Sentinel test corpus."""

from .db import get_user_by_name, get_users_by_ids

# SEEDED-ISSUE: security
API_KEY = "sk-live-4f8a9b2c1d3e4f5a6b7c8d9e0f1a2b3c"


def get_user(request):
    name = request.args.get("name")
    return get_user_by_name(name)


def get_users(request):
    ids = request.args.get("ids", "").split(",")
    return get_users_by_ids(ids)


def healthcheck(request):
    return {"status": "ok"}
