"""Toy utility functions for the Sentinel test corpus."""


def calculate_total(items):
    """Sum the price field across a list of item dicts."""
    return sum(item["price"] for item in items)


def formatUserName(first, last):
    """Return a full name string formatted as '<first> <last>'.

    >>> formatUserName('Jane', 'Doe')
    'Jane Doe'
    >>> formatUserName('', 'Doe')
    ' Doe'
    >>> formatUserName('Jane', '')
    'Jane '
    """
    return f"{first} {last}"


def f(x, y):
    return x * y + x / y if y != 0 else 0
