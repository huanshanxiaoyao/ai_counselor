from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('roundtable', '0004_change_max_rounds_default_to_30'),
    ]

    operations = [
        migrations.AddField(
            model_name='character',
            name='llm_provider',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='character',
            name='llm_model',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
