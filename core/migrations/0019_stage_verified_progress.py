from django.db import migrations, models
from django.core.validators import MinValueValidator, MaxValueValidator


class Migration(migrations.Migration):
    dependencies = [("core", "0018_framezone_color")]
    operations = [
        migrations.AddField(model_name="stage", name="verified_progress_percent", field=models.FloatField(blank=True, null=True, validators=[MinValueValidator(0), MaxValueValidator(100)], verbose_name="Подтверждённый физический прогресс, %")),
        migrations.AddField(model_name="stage", name="verified_progress_date", field=models.DateField(blank=True, null=True, verbose_name="Дата замера прогресса")),
        migrations.AddField(model_name="stage", name="verified_progress_note", field=models.TextField(blank=True, verbose_name="Основание подтверждения прогресса")),
        migrations.AddField(model_name="stage", name="expected_finish_date", field=models.DateField(blank=True, null=True, verbose_name="Ожидаемое окончание по оценке ответственного")),
    ]
