"""Customer auth/session services.

Lifecycle transitions live here as explicit operations, never inside ORM
property setters: a session revocation, a challenge consumption, and an
identity binding each have preconditions that a setter cannot express and a
caller cannot see.

These services are transport-agnostic. They take a SQLAlchemy `Session`, a
`Clock`, and provider ports, and they return domain results - no FastAPI
request/response objects, no cookies, no HTTP status codes. That is what lets
them be tested exactly and mounted later without rewriting the logic into route
handlers.
"""
