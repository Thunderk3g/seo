# Hand-rolled migration for the SerpAPI device split. Adds the
# ``device`` column to GapSerpResult so we can persist desktop +
# mobile (+ tablet) probe rows side-by-side, and adds a composite
# (run, engine, device) index so per-device queries stay fast.
# Existing rows get the default "desktop" value, matching what they
# implicitly were before the split.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("seo_ai", "0002_gap_pipeline"),
    ]

    operations = [
        migrations.AddField(
            model_name="gapserpresult",
            name="device",
            field=models.CharField(default="desktop", max_length=16),
        ),
        migrations.AlterModelOptions(
            name="gapserpresult",
            options={"ordering": ("run", "engine", "device", "query_id")},
        ),
        migrations.AddIndex(
            model_name="gapserpresult",
            index=models.Index(
                fields=["run", "engine", "device"],
                name="gap_pipe_serp_run_eng_dev_idx",
            ),
        ),
    ]
