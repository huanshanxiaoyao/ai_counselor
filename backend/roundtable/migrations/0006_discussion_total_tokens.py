from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('roundtable', '0005_character_llm_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='discussion',
            name='total_tokens',
            field=models.IntegerField(default=0),
        ),
    ]
