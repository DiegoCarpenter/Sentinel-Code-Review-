"""Toy utility functions for the Sentinel test corpus."""


def calculate_total(items):
    """Sum the price field across a list of item dicts."""
    return sum(item["price"] for item in items)


def formatUserName(first, last):
    return f"{first} {last}"


def f(x, y):
    return x * y + x / y if y != 0 else 0
