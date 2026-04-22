from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('moodpal', '0002_moodpalsessionevent_moodpalmessage'),
    ]

    operations = [
        migrations.AlterField(
            model_name='moodpalsessionevent',
            name='event_type',
            field=models.CharField(
                choices=[
                    ('crisis_triggered', '危机抢占已触发'),
                    ('summary_generated', '摘要已生成'),
                    ('summary_saved', '摘要已保存'),
                    ('summary_destroyed', '摘要已销毁'),
                    ('raw_messages_destroyed', '原始消息已销毁'),
                ],
                max_length=40,
            ),
        ),
    ]
