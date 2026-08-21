from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('squid', '0011_clean_remaining_blacklists'),
    ]

    operations = [
        migrations.AddField(
            model_name='discoveredsublink',
            name='ai_analysis',
            field=models.JSONField(blank=True, null=True, verbose_name='Análise de IA'),
        ),
        migrations.AddField(
            model_name='discoveredsublink',
            name='ai_analyzed_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Data da Análise de IA'),
        ),
    ]
