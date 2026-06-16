"""
Parse upstream experiment data files (CSV plate maps, concentration tables)
into structured context strings for the LLM.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import NamedTuple


class FileAttachment(NamedTuple):
    name: str
    content: str
    file_type: str  # "csv", "python", "text"


def read_file(path: Path) -> FileAttachment:
    """Read a file and return a structured attachment."""
    suffix = path.suffix.lower()
    content = path.read_text(encoding="utf-8")

    if suffix == ".csv":
        file_type = "csv"
    elif suffix == ".py":
        file_type = "python"
    else:
        file_type = "text"

    return FileAttachment(name=path.name, content=content, file_type=file_type)


def parse_plate_csv(csv_text: str) -> dict[str, list[dict[str, str]]]:
    """
    Parse a CSV that represents plate data. Handles two common formats:

    1. Tabular format: columns like Well, SampleID, Concentration, Volume, etc.
    2. Plate-map format: rows A-H, columns 1-12, with values in cells.

    Returns a dict with:
      - 'headers': list of column names
      - 'rows': list of row dicts
      - 'format': 'tabular' or 'plate_map'
      - 'summary': human-readable summary
    """
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)

    if not rows:
        return {"headers": [], "rows": [], "format": "empty", "summary": "Empty CSV"}

    headers = [h.strip() for h in rows[0]]

    # Detect plate-map format: first column is row letters (A-H/A-P),
    # remaining columns are numbers (1-12 or 1-24)
    is_plate_map = (
        len(headers) > 1
        and headers[0] == ""
        and all(h.isdigit() for h in headers[1:] if h)
    )

    if is_plate_map:
        well_data = []
        for row in rows[1:]:
            if not row or not row[0].strip():
                continue
            row_letter = row[0].strip()
            for col_idx, value in enumerate(row[1:], start=1):
                value = value.strip()
                if value:
                    well_data.append({"well": f"{row_letter}{col_idx}", "value": value})
        return {
            "headers": ["well", "value"],
            "rows": well_data,
            "format": "plate_map",
            "summary": f"Plate map with {len(well_data)} wells containing data",
        }

    # Tabular format
    parsed_rows = []
    for row in rows[1:]:
        if not any(cell.strip() for cell in row):
            continue
        parsed_rows.append(dict(zip(headers, [c.strip() for c in row])))

    return {
        "headers": headers,
        "rows": parsed_rows,
        "format": "tabular",
        "summary": f"Table with {len(parsed_rows)} rows, columns: {', '.join(headers)}",
    }


def format_attachment_context(attachment: FileAttachment) -> str:
    """Format a file attachment as context for the LLM."""
    parts = [
        f'<uploaded_file name="{attachment.name}" type="{attachment.file_type}">',
    ]

    if attachment.file_type == "csv":
        parsed = parse_plate_csv(attachment.content)
        parts.append(f"Format: {parsed['format']}")
        parts.append(f"Summary: {parsed['summary']}")
        parts.append("")
        parts.append("Raw data:")
        parts.append(attachment.content)

        # For tabular data with recognizable concentration/volume columns,
        # add a hint about normalization potential
        if parsed["format"] == "tabular":
            lower_headers = [h.lower() for h in parsed["headers"]]
            has_conc = any(
                kw in h for h in lower_headers for kw in ("conc", "ng", "concentration", "qubit")
            )
            has_well = any(kw in h for h in lower_headers for kw in ("well", "position", "location"))
            if has_conc and has_well:
                parts.append("")
                parts.append(
                    "NOTE: This data contains well positions and concentration values. "
                    "It is likely suitable for normalization calculations "
                    "(computing per-well volumes to reach a target concentration/mass)."
                )
    else:
        parts.append(attachment.content)

    parts.append("</uploaded_file>")
    return "\n".join(parts)


def build_data_context(attachments: list[FileAttachment]) -> str:
    """Build the combined data context string from all attachments."""
    if not attachments:
        return ""
    sections = [format_attachment_context(a) for a in attachments]
    return "\n\n".join(sections)
