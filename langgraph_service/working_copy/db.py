"""Toy DB access layer for the Sentinel test corpus."""


def get_connection():
    # Stand-in for a real DB connection (e.g. sqlite3.connect(...)).
    return None


def execute_query(query, params=()):
    conn = get_connection()
    return conn.execute(query, params).fetchall()


def get_user_by_name(name):
    query = "SELECT * FROM users WHERE name = ?"
    return execute_query(query, (name,))


def get_users_by_ids(ids):
    results = []
    for user_id in ids:
        query = f"SELECT * FROM users WHERE id = {user_id}"
        results.append(execute_query(query))
    return results


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def _test_execute_query_delegates_to_connection():
    """execute_query should call conn.execute with the right args and return rows."""
    import types

    # Build a minimal fake connection whose execute() returns a fetchable object.
    fake_rows = [(1, "alice"), (2, "bob")]

    class FakeCursor:
        def fetchall(self):
            return fake_rows

    class FakeConn:
        def __init__(self):
            self.calls = []

        def execute(self, query, params):
            self.calls.append((query, params))
            return FakeCursor()

    fake_conn = FakeConn()

    import db as _db  # allow the module to be imported by its own name
    original_get_connection = _db.get_connection
    try:
        _db.get_connection = lambda: fake_conn
        result = _db.execute_query("SELECT 1", (42,))
        assert result == fake_rows, f"Expected {fake_rows!r}, got {result!r}"
        assert fake_conn.calls == [("SELECT 1", (42,))], (
            f"Unexpected calls: {fake_conn.calls!r}"
        )
    finally:
        _db.get_connection = original_get_connection


def _test_execute_query_uses_empty_tuple_default():
    """execute_query should default params to an empty tuple."""
    class FakeCursor:
        def fetchall(self):
            return []

    class FakeConn:
        def __init__(self):
            self.calls = []

        def execute(self, query, params):
            self.calls.append((query, params))
            return FakeCursor()

    fake_conn = FakeConn()

    import db as _db
    original_get_connection = _db.get_connection
    try:
        _db.get_connection = lambda: fake_conn
        _db.execute_query("SELECT 2")
        assert fake_conn.calls == [("SELECT 2", ())], (
            f"Unexpected calls: {fake_conn.calls!r}"
        )
    finally:
        _db.get_connection = original_get_connection


if __name__ == "__main__":
    _test_execute_query_delegates_to_connection()
    _test_execute_query_uses_empty_tuple_default()
    print("All execute_query tests passed.")
