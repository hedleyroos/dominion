import pickle

from django.db import models


class EmailMessage(models.Model):
    """Model that represents an email message. `pickled` is a pickled representation
    of a django.core.mail.EmailMessage instance. That class doesn't implement serialization,
    so pickling will have to do."""
    created = models.DateTimeField(auto_now_add=True, editable=False, db_index=True)
    pickled = models.BinaryField(editable=False)
    sent = models.BooleanField(default=False, db_index=True)

    @property
    def unpickled(self):
        return pickle.loads(self.pickled)
