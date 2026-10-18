web: python -m backend.main
worker: celery -A backend.worker.celery_app worker --pool=solo --loglevel=info
