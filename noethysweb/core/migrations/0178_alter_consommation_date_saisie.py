# Generated by Django 3.2.21 on 2024-12-03 19:09

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0177_auto_20241124_2221'),
    ]

    operations = [
        migrations.AlterField(
            model_name='consommation',
            name='date_saisie',
            field=models.DateTimeField(verbose_name='Date de saisie'),
        ),
    ]
