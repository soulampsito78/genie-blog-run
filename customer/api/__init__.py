"""Transport-ready customer API package.

Importing this package is intentionally configuration-free: it does not create
a database engine, open a connection, or mount anything into production
``main.py``.  A future controlled integration can mount ``customer_router``.
"""

from customer.api.router import customer_router, create_customer_test_app

__all__ = ["customer_router", "create_customer_test_app"]
