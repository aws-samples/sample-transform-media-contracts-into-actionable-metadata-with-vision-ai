#!/usr/bin/env python3
"""
MCS (Media Contracts Schema) v1.0 Validator

Validates that analyzer format XML files conform to the MCS base schema structure.
Checks for required parts, proper structure, and common issues.
"""

import sys
import defusedxml.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Tuple
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """Result of validating a format file."""

    file_path: Path
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    parts_implemented: List[str]


class MCSValidator:
    """Validates MCS conformance for analyzer format files."""

    # Required MCS parts for each analyzer type
    REQUIRED_PARTS = {
        "extractor": ["Part 1", "Part 2", "Part 3", "Part 7"],
        "handwriting_analyzer": ["Part 1", "Part 2", "Part 3", "Part 7"],
        "financial": ["Part 1", "Part 2", "Part 5", "Part 6", "Part 7"],
        "rights_clearance": ["Part 1", "Part 2", "Part 5", "Part 6", "Part 7"],
        "regulatory_compliance": ["Part 1", "Part 2", "Part 5", "Part 6", "Part 7"],
        "talent_guild_compliance": ["Part 1", "Part 2", "Part 5", "Part 6", "Part 7"],
        "risk_strategist": [
            "Part 1",
            "Part 2",
            "Part 5",
            "Part 7",
        ],  # Part 6 embedded in Part 5
    }

    OPTIONAL_PARTS = ["Part 3", "Part 4", "Part 6"]

    STANDARD_METADATA_FIELDS = [
        "analyzer_name",
        "schema_version",
        "timestamp",
        "source_document",
        "element_count",
        "confidence",
    ]

    def __init__(self):
        self.results = []

    def validate_file(self, file_path: Path) -> ValidationResult:
        """Validate a single format XML file."""
        errors = []
        warnings = []
        parts_implemented = []

        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
        except ET.ParseError as e:
            return ValidationResult(
                file_path=file_path,
                is_valid=False,
                errors=[f"XML parsing error: {e}"],
                warnings=[],
                parts_implemented=[],
            )

        # Determine analyzer type from file path
        analyzer_name = self._detect_analyzer_name(file_path)
        if not analyzer_name:
            errors.append("Could not determine analyzer name from file path")
            return ValidationResult(
                file_path=file_path,
                is_valid=False,
                errors=errors,
                warnings=warnings,
                parts_implemented=parts_implemented,
            )

        # Find the actual response element (skip response_format wrapper)
        response = root.find(".//response")
        if response is None:
            response = root if root.tag == "response" else None

        if response is None:
            errors.append("No <response> element found")
            return ValidationResult(
                file_path=file_path,
                is_valid=False,
                errors=errors,
                warnings=warnings,
                parts_implemented=parts_implemented,
            )

        # Check Part 1: Envelope
        envelope_result = self._check_envelope(response, analyzer_name)
        if envelope_result["valid"]:
            parts_implemented.append("Part 1")
        errors.extend(envelope_result["errors"])
        warnings.extend(envelope_result["warnings"])

        # Check Part 2: Core Metadata
        metadata_result = self._check_metadata(response)
        if metadata_result["valid"]:
            parts_implemented.append("Part 2")
        errors.extend(metadata_result["errors"])
        warnings.extend(metadata_result["warnings"])

        # Check Part 3: Common Spine (if applicable)
        spine_result = self._check_common_spine(response, analyzer_name)
        if spine_result["implemented"]:
            parts_implemented.append("Part 3")
        errors.extend(spine_result["errors"])
        warnings.extend(spine_result["warnings"])

        # Check Part 4: Topical Analysis (optional)
        if response.find("topical_analysis") is not None:
            parts_implemented.append("Part 4")

        # Check Part 5: Specialized Section
        specialized_result = self._check_specialized(response, analyzer_name)
        if specialized_result["valid"]:
            parts_implemented.append("Part 5")
        errors.extend(specialized_result["errors"])
        warnings.extend(specialized_result["warnings"])

        # Check Part 6: Findings (if applicable)
        findings_result = self._check_findings(response, analyzer_name)
        if findings_result["implemented"]:
            parts_implemented.append("Part 6")
        errors.extend(findings_result["errors"])
        warnings.extend(findings_result["warnings"])

        # Check Part 7: Tags
        tags_result = self._check_tags(response)
        if tags_result["valid"]:
            parts_implemented.append("Part 7")
        errors.extend(tags_result["errors"])
        warnings.extend(tags_result["warnings"])

        # Check MCS reference comment
        if not self._check_mcs_comment(file_path):
            warnings.append("Missing MCS reference comment in file header")

        # Verify all required parts are implemented
        required_parts = self.REQUIRED_PARTS.get(analyzer_name, [])
        missing_parts = [p for p in required_parts if p not in parts_implemented]
        if missing_parts:
            errors.append(f"Missing required parts: {', '.join(missing_parts)}")

        is_valid = len(errors) == 0

        return ValidationResult(
            file_path=file_path,
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            parts_implemented=parts_implemented,
        )

    def _detect_analyzer_name(self, file_path: Path) -> str:
        """Detect analyzer name from file path."""
        path_parts = file_path.parts
        if "extractor" in path_parts:
            return "extractor"
        elif "handwriting_analyzer" in path_parts:
            return "handwriting_analyzer"
        elif "financial" in path_parts:
            return "financial"
        elif "rights_clearance" in path_parts:
            return "rights_clearance"
        elif "regulatory_compliance" in path_parts:
            return "regulatory_compliance"
        elif "talent_guild_compliance" in path_parts:
            return "talent_guild_compliance"
        elif "risk_strategist" in path_parts:
            return "risk_strategist"
        return ""

    def _check_mcs_comment(self, file_path: Path) -> bool:
        """Check if file contains MCS reference comment."""
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read(1000)  # Check first 1000 chars
            return "Media Contracts Schema" in content or "MCS" in content

    def _check_envelope(self, response: ET.Element, analyzer_name: str) -> Dict:
        """Check Part 1: Envelope attributes."""
        errors = []
        warnings = []

        required_attrs = ["schema_version", "job_id", "timestamp"]

        # Check for analyzer attribute
        if "analyzer" not in response.attrib:
            errors.append("Part 1: Missing 'analyzer' attribute in envelope")
        elif response.attrib["analyzer"] != analyzer_name:
            warnings.append(
                f"Part 1: analyzer='{response.attrib['analyzer']}' doesn't match expected '{analyzer_name}'"
            )

        # Check required attributes
        for attr in required_attrs:
            if attr not in response.attrib:
                errors.append(
                    f"Part 1: Missing required attribute '{attr}' in envelope"
                )

        # Check schema version
        if (
            "schema_version" in response.attrib
            and response.attrib["schema_version"] != "1.0"
        ):
            warnings.append(
                f"Part 1: schema_version is '{response.attrib['schema_version']}', expected '1.0'"
            )

        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}

    def _check_metadata(self, response: ET.Element) -> Dict:
        """Check Part 2: Core Metadata."""
        errors = []
        warnings = []

        metadata = response.find("metadata")
        if metadata is None:
            errors.append("Part 2: Missing <metadata> section")
            return {"valid": False, "errors": errors, "warnings": warnings}

        # Check for standard fields
        missing_fields = []
        for field in self.STANDARD_METADATA_FIELDS:
            if metadata.find(field) is None:
                missing_fields.append(field)

        if missing_fields:
            warnings.append(
                f"Part 2: Missing recommended metadata fields: {', '.join(missing_fields)}"
            )

        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}

    def _check_common_spine(self, response: ET.Element, analyzer_name: str) -> Dict:
        """Check Part 3: Common Spine (optional for some analyzers)."""
        errors = []
        warnings = []

        spine = response.find("common_spine")
        implemented = spine is not None

        # Check if spine is required for this analyzer
        requires_spine = analyzer_name in ["extractor", "handwriting_analyzer"]

        if requires_spine and not implemented:
            errors.append(
                f"Part 3: Missing <common_spine> section (required for {analyzer_name})"
            )

        if implemented:
            # Check structure
            elements = spine.findall("element")
            if len(elements) == 0:
                warnings.append(
                    "Part 3: <common_spine> is present but contains no elements"
                )

            # Check element_count attribute
            if "element_count" not in spine.attrib:
                warnings.append(
                    "Part 3: <common_spine> missing 'element_count' attribute"
                )

        return {"implemented": implemented, "errors": errors, "warnings": warnings}

    def _check_specialized(self, response: ET.Element, analyzer_name: str) -> Dict:
        """Check Part 5: Specialized Section."""
        errors = []
        warnings = []

        specialized = response.find("specialized")
        if specialized is None:
            errors.append("Part 5: Missing <specialized> section")
            return {"valid": False, "errors": errors, "warnings": warnings}

        # Check type attribute
        if "type" not in specialized.attrib:
            errors.append("Part 5: <specialized> missing 'type' attribute")

        # Check that specialized section has content
        if len(list(specialized)) == 0:
            warnings.append("Part 5: <specialized> section is empty")

        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}

    def _check_findings(self, response: ET.Element, analyzer_name: str) -> Dict:
        """Check Part 6: Findings (not applicable to extractor, handwriting_analyzer, and risk_strategist)."""
        errors = []
        warnings = []

        # Findings are optional for extractor, handwriting_analyzer (hybrid), and risk_strategist (embeds in specialized)
        if analyzer_name in ["extractor", "handwriting_analyzer", "risk_strategist"]:
            return {"implemented": False, "errors": [], "warnings": []}

        # Look for various findings section patterns
        findings_patterns = [
            "findings",
            "financial_findings",
            "rights_findings",
            "regulatory_findings",
            "talent_findings",
            "risk_findings",
        ]

        findings = None
        for pattern in findings_patterns:
            findings = response.find(pattern)
            if findings is not None:
                break

        implemented = findings is not None

        if not implemented:
            errors.append(
                "Part 6: Missing findings section (specialist analyzers must have findings)"
            )

        return {"implemented": implemented, "errors": errors, "warnings": warnings}

    def _check_tags(self, response: ET.Element) -> Dict:
        """Check Part 7: Tags."""
        errors = []
        warnings = []

        tags = response.find("tags")
        if tags is None:
            errors.append("Part 7: Missing <tags> section")
            return {"valid": False, "errors": errors, "warnings": warnings}

        # Check that tags section has at least one tag element
        tag_elements = tags.findall("tag")
        if len(tag_elements) == 0:
            warnings.append(
                "Part 7: <tags> section is present but contains no <tag> elements"
            )

        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}

    def validate_directory(self, directory: Path) -> List[ValidationResult]:
        """Validate all format XML files in a directory tree."""
        results = []

        # Find all *_format.xml files
        format_files = list(directory.rglob("*_format.xml"))

        for file_path in format_files:
            result = self.validate_file(file_path)
            results.append(result)

        return results

    def print_results(self, results: List[ValidationResult]):
        """Print validation results in a readable format."""
        print("\n" + "=" * 80)
        print("MCS v1.0 Validation Results")
        print("=" * 80 + "\n")

        total_files = len(results)
        valid_files = sum(1 for r in results if r.is_valid)
        invalid_files = total_files - valid_files

        for result in results:
            status = "✅ VALID" if result.is_valid else "❌ INVALID"
            print(f"{status}: {result.file_path.name}")
            print(f"  Parts implemented: {', '.join(result.parts_implemented)}")

            if result.errors:
                print(f"  Errors ({len(result.errors)}):")
                for error in result.errors:
                    print(f"    - {error}")

            if result.warnings:
                print(f"  Warnings ({len(result.warnings)}):")
                for warning in result.warnings:
                    print(f"    - {warning}")

            print()

        print("=" * 80)
        print(f"Summary: {valid_files}/{total_files} files are valid")
        if invalid_files > 0:
            print(f"⚠️  {invalid_files} file(s) have errors that must be fixed")
        print("=" * 80 + "\n")

        return invalid_files == 0


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python validate_mcs.py <directory_or_file>")
        print("\nExamples:")
        print("  python validate_mcs.py media_contracts_agents/")
        print(
            "  python validate_mcs.py media_contracts_agents/financial/financial_format.xml"
        )
        sys.exit(1)

    target_path = Path(sys.argv[1])

    if not target_path.exists():
        print(f"Error: Path '{target_path}' does not exist")
        sys.exit(1)

    validator = MCSValidator()

    if target_path.is_file():
        # Validate single file
        result = validator.validate_file(target_path)
        validator.print_results([result])
        sys.exit(0 if result.is_valid else 1)
    else:
        # Validate directory
        results = validator.validate_directory(target_path)
        all_valid = validator.print_results(results)
        sys.exit(0 if all_valid else 1)


if __name__ == "__main__":
    main()
