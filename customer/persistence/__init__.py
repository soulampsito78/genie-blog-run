"""Customer persistence layer (SQLAlchemy ORM + Alembic-managed schema).

Schema authority is Alembic ONLY. Nothing in this package may issue DDL at
runtime: no `metadata.create_all()` in application code, no ad-hoc ALTER. The
single migration environment lives in `customer/migrations` and is driven by
the repository-root `alembic.ini`.
"""

from customer.persistence.base import CustomerBase, customer_metadata

__all__ = ["CustomerBase", "customer_metadata"]
