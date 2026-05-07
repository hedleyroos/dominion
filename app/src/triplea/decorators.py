import functools
import inspect

from asgiref.sync import sync_to_async
from django.db import close_old_connections


def django(fn: callable) -> callable:
    """Ensure the database connection is healthy before and after the function runs.

    Works for both sync and async callables. Intended for use in long-running
    Celery workers or async view helpers where connections can go stale.
    """
    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            await sync_to_async(close_old_connections)()
            result = await fn(*args, **kwargs)
            await sync_to_async(close_old_connections)()
            return result
        return async_wrapper

    @functools.wraps(fn)
    def sync_wrapper(*args, **kwargs):
        close_old_connections()
        result = fn(*args, **kwargs)
        close_old_connections()
        return result
    return sync_wrapper
