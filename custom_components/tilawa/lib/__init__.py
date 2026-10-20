"""Pure-Python core of Tilawa.

Nothing in this package imports Home Assistant. It is driven through injected
collaborators: an ``aiohttp.ClientSession`` for HTTP, and a ``run_blocking``
callable (``hass.async_add_executor_job`` in Home Assistant) for file I/O.
"""
