"""Toy DB access layer for the Sentinel test corpus."""


def get_connection(db_path=":memory:"):
    """Return a database connection.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.  Defaults to an in-memory database
        so that callers in tests can pass a real path without side-effects.

    Returns
    -------
    sqlite3.Connection or None
        A live connection when *db_path* is provided, otherwise ``None`` to
        preserve the existing stand-in behaviour.
    """
    import sqlite3  # local import keeps the module importable without sqlite3

    if db_path is None:
        # Stand-in for environments where no real DB is configured.
        return None
    return sqlite3.connect(db_path)


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
