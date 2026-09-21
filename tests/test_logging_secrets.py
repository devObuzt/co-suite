"""httpx logs the full request URL at INFO, so any secret in the path lands in
the deploy logs. The worker printed the Telegram bot token in full on every
capacity alert because the silencing lived in api/main.py, which the worker
never imports.
"""
import logging

from api.core.observability import configure_logging


def test_configure_logging_silences_httpx_url_logging():
    logging.getLogger("httpx").setLevel(logging.INFO)  # the default
    configure_logging()
    assert logging.getLogger("httpx").level >= logging.WARNING


def test_worker_entrypoint_goes_through_configure_logging():
    """The worker must get this without importing api.main — that was the bug."""
    import inspect

    from api.workers import generation_queue

    source = inspect.getsource(generation_queue)
    assert "configure_logging()" in source
    assert "api.main" not in source and "from ..main" not in source
