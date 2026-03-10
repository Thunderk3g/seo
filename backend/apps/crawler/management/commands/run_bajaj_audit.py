import os
import argparse
from django.core.management.base import BaseCommand, CommandError
from apps.crawler.services.bajaj_audit_service import BajajAuditService

class Command(BaseCommand):
    help = "Run the Bajaj Allianz Life Deep Partner Website Audit"

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            type=str,
            default=r"C:\Users\Diwakar.Adhikari01\Desktop\SEO\Partners_Site_List.xlsx",
            help="Path to the input Excel file containing partner domains.",
        )
        parser.add_argument(
            "--output",
            type=str,
            default="Bajaj_Allianz_Life_Deep_Audit.xlsx",
            help="Output path for the final summary Excel file.",
        )
        parser.add_argument(
            "--progress",
            type=str,
            default="_crawl_progress.csv",
            help="Path for saving intermittent progress.",
        )

    def handle(self, *args, **options):
        input_file = options["input"]
        output_file = options["output"]
        progress_file = options["progress"]

        if not os.path.exists(input_file):
            raise CommandError(f"Input file not found at: {input_file}")

        self.stdout.write(self.style.NOTICE(f"Starting Bajaj Audit..."))
        self.stdout.write(f"Input: {input_file}")
        self.stdout.write(f"Output will be saved to: {output_file}")
        
        try:
            service = BajajAuditService(
                input_file=input_file,
                output_file=output_file,
                progress_csv=progress_file,
            )
            service.run_audit()
            
            self.stdout.write(self.style.SUCCESS(f"\nAudit completed successfully! Check the output at {output_file}"))
        except Exception as e:
            raise CommandError(f"An error occurred during the audit: {str(e)}")
