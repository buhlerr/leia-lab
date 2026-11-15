#!/bin/sh
set -e
python -m src.management.manage migrate --noinput
python -m src.management.manage collectstatic --noinput
python -m src.management.manage shell <<'PYEOF'
import os
from django.contrib.auth import get_user_model

User = get_user_model()
username = os.environ["DJANGO_SUPERUSER_USERNAME"]
user, created = User.objects.get_or_create(
    username=username,
    defaults={"email": os.environ.get("DJANGO_SUPERUSER_EMAIL", "")},
)
user.set_password(os.environ["DJANGO_SUPERUSER_PASSWORD"])
user.is_superuser = True
user.is_staff = True
user.save()
print("superuser", username, "ok (created=%s)" % created)
PYEOF
exec gunicorn src.management.leia_admin.wsgi:application -b 0.0.0.0:8000 --workers 2 --access-logfile -
