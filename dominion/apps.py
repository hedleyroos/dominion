from django.apps import AppConfig
from django.db import Error as DatabaseError


class DominionConfig(AppConfig):
    name = "dominion"

    def ready(self):
        from dominion import create_initial_data
        from dominion import handlers

        # Creation may fail on a clean database the first time. It's not a problem,
        # since subsequent operations will allow the next attempt to succeed
        try:
            create_initial_data()
        except DatabaseError:
            pass
