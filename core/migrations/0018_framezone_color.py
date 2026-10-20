from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("core", "0017_registrationrequest")]
    operations = [migrations.AddField(model_name="framezone", name="color", field=models.CharField("Цвет зоны", max_length=7, blank=True, default=""))]
