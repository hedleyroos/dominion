from django.apps import AppConfig
from django.db.utils import ProgrammingError


class TripleAConfig(AppConfig):
    name = "triplea"

    def ready(self):
        from triplea import create_initial_data
        from triplea import handlers

        # Creation may fail on a clean database the first time. It's not a problem,
        # since subsequent operations will allow the next attempt to succeed.
        try:
            create_initial_data()
        except ProgrammingError:
            pass
