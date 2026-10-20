from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("core", "0016_zone_kind")]
    operations = [migrations.CreateModel(name="RegistrationRequest", fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("email", models.EmailField(max_length=254, unique=True)),
        ("full_name", models.CharField(max_length=150)),
        ("password_hash", models.CharField(max_length=256)),
        ("created_at", models.DateTimeField(auto_now_add=True)),
    ], options={"ordering":["-created_at"]})]
