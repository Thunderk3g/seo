"""Add ``ExportRecord.content_bytes`` for binary export bodies (xlsx, etc.).

CSV/XML/JSON kinds keep using the ``content`` TextField; the new column
holds the bytes for openpyxl-generated workbooks where utf-8 encoding
through TextField would corrupt the zip container.

Also relabels the ``issues.xlsx`` kind from "Issues (CSV)" to
"Issues (XLSX)" now that the body is a real Excel file.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crawl_sessions", "0004_add_exportrecord"),
    ]

    operations = [
        migrations.AddField(
            model_name="exportrecord",
            name="content_bytes",
            field=models.BinaryField(
                blank=True,
                default=b"",
                help_text="Raw bytes for binary export kinds (e.g. .xlsx).",
            ),
        ),
        migrations.AlterField(
            model_name="exportrecord",
            name="kind",
            field=models.CharField(
                choices=[
                    ("urls.csv", "URLs (CSV)"),
                    ("issues.xlsx", "Issues (XLSX)"),
                    ("sitemap.xml", "Sitemap (XML)"),
                    ("broken-links.csv", "Broken Links (CSV)"),
                    ("redirects.csv", "Redirects (CSV)"),
                    ("metadata.json", "Metadata (JSON)"),
                ],
                db_index=True,
                max_length=32,
            ),
        ),
    ]
