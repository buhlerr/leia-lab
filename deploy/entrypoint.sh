#!/bin/sh
# Sobe o admin. Requer DATABASE_URL e DJANGO_SECRET_KEY (o settings recusa subir sem ela).
set -e

# So as tabelas do Django (django_*/auth_*): as da Leia sao managed=False e vem do schema.sql.
python -m src.management.manage migrate --noinput
python -m src.management.manage collectstatic --noinput

# Superusuario inicial so se pedido e so se ainda nao existir (a senha nao e redefinida a cada boot).
if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ]; then
  python -m src.management.manage createsuperuser --noinput \
    --username "$DJANGO_SUPERUSER_USERNAME" --email "${DJANGO_SUPERUSER_EMAIL:-}" 2>/dev/null \
    && echo "superusuario $DJANGO_SUPERUSER_USERNAME criado" \
    || echo "superusuario $DJANGO_SUPERUSER_USERNAME ja existe"
fi

# gunicorn com timeout 330 s: a view de "Nova analise" espera a API ate 300 s e ainda responde.
exec gunicorn src.management.leia_admin.wsgi:application -b 0.0.0.0:8000 --workers 2 --timeout 330 --access-logfile -
