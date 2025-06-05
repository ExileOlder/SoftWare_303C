from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),  # 确保依赖于初始迁移
    ]

    operations = [
        migrations.AddField(
            model_name='guest',
            name='check_in_count',
            field=models.IntegerField(default=1, verbose_name='入住次数'),
        ),
    ] 