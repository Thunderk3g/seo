"""Structured Data Extraction (JSON-LD / Schema.org).

Extracts and validates structured data from parsed pages.
Powers the enhancement panels for breadcrumb validity,
review snippets, and schema warnings.
"""

from dataclasses import dataclass, field
from typing import Optional

from apps.common.constants import SCHEMA_TYPES
from apps.common.logging import parse_logger


@dataclass
class SchemaItem:
    """A single structured data block extracted from a page."""
    schema_type: str
    raw_json: dict = field(default_factory=dict)
    is_valid: bool = True
    error_message: str = ""

    @property
    def type_label(self) -> str:
        """Readable label for the schema type."""
        return self.schema_type.replace("http://schema.org/", "").replace("https://schema.org/", "")


class SchemaExtractor:
    """Extract and validate JSON-LD structured data from parsed pages.

    Takes the json_ld list from ParseResult and produces
    validated SchemaItem objects for storage.
    """

    # Required fields per schema type for basic validation
    REQUIRED_FIELDS = {
        "Product": ["name"],
        "Article": ["headline"],
        "FAQ": ["mainEntity"],
        "FAQPage": ["mainEntity"],
        "Review": ["itemReviewed"],
        "BreadcrumbList": ["itemListElement"],
        "HowTo": ["step"],
        "Event": ["name", "startDate"],
        "Recipe": ["name"],
        "JobPosting": ["title", "datePosted"],
        "LocalBusiness": ["name", "address"],
        "Organization": ["name"],
        "Video": ["name"],
        "VideoObject": ["name"],
    }

    def extract(self, json_ld_blocks: list[dict]) -> list[SchemaItem]:
        """Extract and validate structured data from JSON-LD blocks.

        Args:
            json_ld_blocks: List of parsed JSON-LD dicts from the HTML parser

        Returns:
            List of validated SchemaItem objects
        """
        results: list[SchemaItem] = []

        for block in json_ld_blocks:
            if not isinstance(block, dict):
                continue

            # Handle @graph containers
            if "@graph" in block and isinstance(block["@graph"], list):
                for sub_block in block["@graph"]:
                    item = self._process_block(sub_block)
                    if item:
                        results.append(item)
            else:
                item = self._process_block(block)
                if item:
                    results.append(item)

        return results

    def _process_block(self, block: dict) -> Optional[SchemaItem]:
        """Process a single JSON-LD block into a SchemaItem."""
        schema_type = self._extract_type(block)
        if not schema_type:
            return None

        is_valid, error = self._validate(block, schema_type)

        return SchemaItem(
            schema_type=schema_type,
            raw_json=block,
            is_valid=is_valid,
            error_message=error,
        )

    @staticmethod
    def _extract_type(block: dict) -> str:
        """Extract the schema @type from a JSON-LD block."""
        raw_type = block.get("@type", "")

        if isinstance(raw_type, list):
            raw_type = raw_type[0] if raw_type else ""

        if not raw_type:
            return ""

        # Strip schema.org prefix
        clean = (
            raw_type
            .replace("http://schema.org/", "")
            .replace("https://schema.org/", "")
        )
        return clean

    def _validate(self, block: dict, schema_type: str) -> tuple[bool, str]:
        """Basic validation of required fields for known schema types.

        Returns (is_valid, error_message).
        """
        required = self.REQUIRED_FIELDS.get(schema_type, [])
        if not required:
            # Unknown type: assume valid (no required field rules)
            return True, ""

        missing = [f for f in required if f not in block]
        if missing:
            error = f"Missing required fields: {', '.join(missing)}"
            return False, error

        return True, ""

    @staticmethod
    def get_schema_summary(items: list[SchemaItem]) -> dict:
        """Generate a summary of detected schema types."""
        summary: dict[str, dict] = {}
        for item in items:
            if item.schema_type not in summary:
                summary[item.schema_type] = {"count": 0, "valid": 0, "invalid": 0}
            summary[item.schema_type]["count"] += 1
            if item.is_valid:
                summary[item.schema_type]["valid"] += 1
            else:
                summary[item.schema_type]["invalid"] += 1
        return summary
