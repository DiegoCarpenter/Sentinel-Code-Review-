"""Toy DB access layer for the Sentinel test corpus."""


def get_connection():
    # Stand-in for a real DB connection (e.g. sqlite3.connect(...)).
    return None


def execute_query(query):
    conn = get_connection()
    return conn.execute(query).fetchall()


# SEEDED-ISSUE: security
def get_user_by_name(name):
    query = "SELECT * FROM users WHERE name = '" + name + "'"
    return execute_query(query)


def get_users_by_ids(ids):
    results = []
    # SEEDED-ISSUE: performance
    for user_id in ids:
        query = f"SELECT * FROM users WHERE id = {user_id}"
        results.append(execute_query(query))
    return results
