"""Cross-cutting concerns: configuration, logging, errors.

`core` means "used by every layer and depending on none of them". A module
here may not import from `app.api`, `app.services` or `db`.
"""
