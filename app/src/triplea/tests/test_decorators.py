from unittest.mock import call, patch

from django.test import TestCase

from triplea.decorators import django


class DecoratorsTestCase(TestCase):
    def test_sync_wrapper_calls_close_old_connections(self):
        with patch("triplea.decorators.close_old_connections") as mock_close:
            @django
            def my_func():
                return 42

            result = my_func()

        self.assertEqual(result, 42)
        self.assertEqual(mock_close.call_count, 2)

    async def test_async_wrapper_calls_close_old_connections(self):
        with patch("triplea.decorators.close_old_connections") as mock_close:
            @django
            async def my_func():
                return 42

            result = await my_func()

        self.assertEqual(result, 42)
        self.assertEqual(mock_close.call_count, 2)

    def test_sync_wrapper_preserves_function_metadata(self):
        @django
        def my_func():
            """Docstring."""

        self.assertEqual(my_func.__name__, "my_func")
        self.assertEqual(my_func.__doc__, "Docstring.")

    async def test_async_wrapper_preserves_function_metadata(self):
        @django
        async def my_func():
            """Docstring."""

        self.assertEqual(my_func.__name__, "my_func")
        self.assertEqual(my_func.__doc__, "Docstring.")

    def test_sync_wrapper_passes_args_and_kwargs(self):
        @django
        def add(a, b=0):
            return a + b

        self.assertEqual(add(3, b=4), 7)

    async def test_async_wrapper_passes_args_and_kwargs(self):
        @django
        async def add(a, b=0):
            return a + b

        self.assertEqual(await add(3, b=4), 7)

    def test_sync_wrapper_propagates_exceptions(self):
        @django
        def boom():
            raise ValueError("oops")

        with self.assertRaises(ValueError):
            boom()

    async def test_async_wrapper_propagates_exceptions(self):
        @django
        async def boom():
            raise ValueError("oops")

        with self.assertRaises(ValueError):
            await boom()
