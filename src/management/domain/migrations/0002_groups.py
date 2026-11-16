"""Grupos de permissao (decisao Q4): ``editor`` muda regras e a base normativa; ``leitor`` so ve.

Ninguem, nem o editor, tem escrita em historico, analises ou trilha: o admin nega (ModelAdmin
so leitura) e o banco tambem (grant + gatilho). So migra tabelas ``auth_*``: nenhum DDL da Leia.
"""

from django.contrib.auth.management import create_permissions
from django.db import migrations

EDITABLE = ["minutatype", "theme", "riskmatrix", "prompt", "kbdoc"]
READ_ONLY = ["domainhistory", "analysis", "analysistrail", "kbchunk"]


def create_groups(apps, schema_editor):
    # As permissoes so existem depois do post_migrate; criar aqui para a migracao ser autossuficiente.
    for app_config in apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, verbosity=0)
        app_config.models_module = None
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    def perms(models, actions):
        codenames = [f"{a}_{m}" for m in models for a in actions]
        found = list(Permission.objects.filter(content_type__app_label="domain", codename__in=codenames))
        assert len(found) == len(codenames), sorted(set(codenames) - {p.codename for p in found})
        return found

    editor, _ = Group.objects.get_or_create(name="editor")
    editor.permissions.set(perms(EDITABLE, ("add", "change", "delete", "view")) + perms(READ_ONLY, ("view",)))
    leitor, _ = Group.objects.get_or_create(name="leitor")
    leitor.permissions.set(perms(EDITABLE + READ_ONLY, ("view",)))


def drop_groups(apps, schema_editor):
    apps.get_model("auth", "Group").objects.filter(name__in=["editor", "leitor"]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("domain", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(create_groups, drop_groups)]
