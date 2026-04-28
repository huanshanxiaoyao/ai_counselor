from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('moodpal', '0003_alter_moodpalsessionevent_event_type'),
    ]

    operations = [
        migrations.AlterField(
            model_name='moodpalsession',
            name='persona_id',
            field=models.CharField(
                choices=[
                    ('master_guide', '全能主理人'),
                    ('logic_brother', '逻辑派的邻家哥哥'),
                    ('empathy_sister', '共情派的知心学姐'),
                    ('insight_mentor', '深挖派的心理学前辈'),
                ],
                max_length=32,
            ),
        ),
    ]
