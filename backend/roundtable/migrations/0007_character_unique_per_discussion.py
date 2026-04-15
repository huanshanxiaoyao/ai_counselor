from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('roundtable', '0006_discussion_total_tokens'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='character',
            constraint=models.UniqueConstraint(
                fields=['discussion', 'name'],
                name='unique_character_per_discussion',
            ),
        ),
    ]
