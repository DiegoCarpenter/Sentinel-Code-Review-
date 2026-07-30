"""Toy Flask-style API layer for the Sentinel test corpus."""

import os

from .db import get_user_by_name, get_users_by_ids

API_KEY = os.environ["API_KEY"]


def get_user(request):
    name = request.args.get("name")
    return get_user_by_name(name)


def get_users(request):
    ids = request.args.get("ids", "").split(",")
    return get_users_by_ids(ids)


def healthcheck(request):
    return {"status": "ok"}
