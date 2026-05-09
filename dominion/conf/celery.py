import os
import sys

from celery import Celery
from celery.signals import task_prerun
from django.db import close_old_connections
from environs import Env


env = Env()


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dominion.conf.settings')


# The result backend must be Redis. RabbitMQ has issues when used as a result
# backend.
backend = env.str("CELERY_BACKEND", "redis://localhost:6379/3")
if not backend.startswith("redis:"):
    raise RuntimeError("Celery backend must be redis")

app = Celery(
    "dominion",
    broker=env.str("CELERY_BROKER", "amqp://localhost:5672//"),
    backend=backend,
)

app.conf["task_always_eager"] = env.bool("CELERY_ALWAYS_EAGER", False)
app.conf["task_default_queue"] = queue = env.str("CELERY_DEFAULT_QUEUE", "dominion")

# Our tasks are idempotent
app.conf["task_acks_late"] = True

# Fine tuning
app.conf["result_expires"] = 604800
app.conf["task_eager_propagates"] = True
app.conf["task_reject_on_worker_lost"] = True

# Relax timeout because we may run over the internet
app.conf["broker_heartbeat"] = 300

app.autodiscover_tasks()


# Ensure Django 4.1 CONN_HEALTH_CHECKS is handled
@task_prerun.connect
def on_task_prerun(sender=None, headers=None, body=None, **kwargs):
    if not app.conf["task_always_eager"]:
        close_old_connections()


if __name__ == "__main__":
    app.start()
