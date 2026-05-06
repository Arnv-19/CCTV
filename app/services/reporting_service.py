from __future__ import annotations

import io
import math
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo
from xml.sax.saxutils import escape

from app.config import get_config
from app.db.models import Alert


REPORT_HEADERS = [
    "DATE",
    "TIME",
    "CAMERA ID",
    "LOCATION",
    "WITHOUT HELMET",
    "WITHOUT BOOT",
    "WITHOUT GLOVES",
    "WITHOUT VEST",
    "SAFE ZONE",
    "OFF HOURS",
]


VIOLATION_BUCKETS = {
    "no-hardhat": "without_helmet",
    "no_hardhat": "without_helmet",
    "no-helmet": "without_helmet",
    "no_helmet": "without_helmet",
    "without helmet": "without_helmet",
    "no-shoes": "without_boot",
    "no_shoes": "without_boot",
    "no-shoe": "without_boot",
    "no_shoe": "without_boot",
    "no-boot": "without_boot",
    "no_boot": "without_boot",
    "no-boots": "without_boot",
    "no_boots": "without_boot",
    "without boot": "without_boot",
    "without boots": "without_boot",
    "no-gloves": "without_gloves",
    "no_gloves": "without_gloves",
    "without gloves": "without_gloves",
    "no-safety-vest": "without_vest",
    "no-safety vest": "without_vest",
    "no_safety_vest": "without_vest",
    "no-vest": "without_vest",
    "no_vest": "without_vest",
    "without vest": "without_vest",
    "safe_zone": "safe_zone",
    "safe zone": "safe_zone",
    "inside_safe_zone": "safe_zone",
    "off_hours": "off_hours",
    "off hours": "off_hours",
    "after_hours": "off_hours",
}

IST_TZ = ZoneInfo("Asia/Kolkata")


@dataclass
class DailyReportRow:
    date: str
    time: str
    camera_id: int
    location: str
    without_helmet: int
    without_boot: int
    without_gloves: int
    without_vest: int
    safe_zone: str
    off_hours: str

    def as_list(self) -> list[str | int]:
        return [
            self.date,
            self.time,
            self.camera_id,
            self.location,
            self.without_helmet,
            self.without_boot,
            self.without_gloves,
            self.without_vest,
            self.safe_zone,
            self.off_hours,
        ]


@dataclass
class ReportRenderContext:
    report_label: str
    filename_date_label: str
    generated_at_label: str
    total_rows: int


def _normalize_key(value: str | None) -> str:
    return (value or "").strip().lower().replace("_", " ").replace("-", " ")


def _bucket_for_alert(alert: Alert) -> str | None:
    candidates = [
        (alert.violation_type or "").strip().lower(),
        (alert.model_name or "").strip().lower(),
        _normalize_key(alert.violation_type),
        _normalize_key(alert.model_name),
    ]
    for candidate in candidates:
        candidate = candidate.replace("  ", " ")
        bucket = VIOLATION_BUCKETS.get(candidate)
        if bucket:
            return bucket
    return None


def _camera_location_map() -> dict[int, str]:
    cfg = get_config()
    titles = cfg.get("camera_titles", []) or []
    return {
        idx: (title or f"Camera {idx}")
        for idx, title in enumerate(titles)
    }


def _resolve_location(camera_id: int, location_map: dict[int, str]) -> str:
    if (camera_id - 1) in location_map:
        return location_map[camera_id - 1]
    if camera_id in location_map:
        return location_map[camera_id]
    return f"Camera {camera_id}"


def _report_window(report_date: date) -> tuple[datetime, datetime]:
    start_dt = datetime.combine(report_date, time.min)
    end_dt = start_dt + timedelta(days=1)
    return start_dt, end_dt


def build_daily_report_rows(
    alerts: Iterable[Alert],
    report_date: date,
    *,
    include_dummy_data: bool = False,
) -> list[DailyReportRow]:
    location_map = _camera_location_map()
    rows: list[DailyReportRow] = []
    for alert in sorted(alerts, key=lambda item: (item.triggered_at, item.camera_id, item.id)):
        row_date = (alert.triggered_at or datetime.utcnow()).strftime("%Y-%m-%d")
        row_time = (alert.triggered_at or datetime.utcnow()).strftime("%H:%M:%S")
        bucket = _bucket_for_alert(alert)
        rows.append(
            DailyReportRow(
                date=row_date,
                time=row_time,
                camera_id=alert.camera_id,
                location=_resolve_location(alert.camera_id, location_map),
                without_helmet=1 if bucket == "without_helmet" else 0,
                without_boot=1 if bucket == "without_boot" else 0,
                without_gloves=1 if bucket == "without_gloves" else 0,
                without_vest=1 if bucket == "without_vest" else 0,
                safe_zone="YES" if bucket == "safe_zone" else "NO",
                off_hours="YES" if bucket == "off_hours" else "NO",
            )
        )
    if not rows and include_dummy_data:
        return build_dummy_report_rows(report_date)
    return rows


def build_dummy_report_rows(report_date: date) -> list[DailyReportRow]:
    samples = [
        ("12:03:24", 1, 0, 0, 0, 0, "NO", "NO"),
        ("14:15:26", 1, 3, 2, 1, 1, "YES", "NO"),
        ("14:17:09", 2, 5, 1, 0, 2, "NO", "YES"),
        ("14:18:45", 3, 0, 0, 4, 1, "YES", "NO"),
    ]
    rows: list[DailyReportRow] = []
    for row_time, camera_id, helmet, boot, gloves, vest, safe_zone, off_hours in samples:
        rows.append(
            DailyReportRow(
                date=report_date.isoformat(),
                time=row_time,
                camera_id=camera_id,
                location=f"Plant {camera_id}",
                without_helmet=helmet,
                without_boot=boot,
                without_gloves=gloves,
                without_vest=vest,
                safe_zone=safe_zone,
                off_hours=off_hours,
            )
        )
    return rows


def build_daily_report_filename(report_date: date, extension: str) -> str:
    return build_report_filename(report_date.isoformat(), extension)


def build_report_filename(date_label: str, extension: str) -> str:
    safe_label = (date_label or "report").strip().replace(" ", "_").replace("/", "-")
    return f"daily_alert_report_{safe_label}.{extension.lstrip('.')}"


def build_report_context(
    *,
    report_date: date,
    date_from: date | None = None,
    date_to: date | None = None,
    total_rows: int = 0,
) -> ReportRenderContext:
    if date_from and date_to:
        if date_from == date_to:
            label = date_from.isoformat()
            report_label = f"Report Date: {label}"
            filename_label = label
        else:
            report_label = f"Report Date: {date_from.isoformat()} to {date_to.isoformat()}"
            filename_label = f"{date_from.isoformat()}_to_{date_to.isoformat()}"
    elif date_from:
        label = date_from.isoformat()
        report_label = f"Report Date: {label}"
        filename_label = label
    elif date_to:
        label = date_to.isoformat()
        report_label = f"Report Date: {label}"
        filename_label = label
    else:
        label = report_date.isoformat()
        report_label = f"Report Date: {label}"
        filename_label = label

    generated_at = datetime.now(IST_TZ).strftime("%I:%M:%S %p IST").lstrip("0")
    return ReportRenderContext(
        report_label=report_label,
        filename_date_label=filename_label,
        generated_at_label=f"Generated At: {generated_at}",
        total_rows=total_rows,
    )


def render_daily_report_xlsx(
    rows: list[DailyReportRow],
    report_date: date,
    context: ReportRenderContext | None = None,
) -> bytes:
    context = context or build_report_context(report_date=report_date, total_rows=len(rows))
    sheet_rows = [
        ["AXIS CCTV ALERT REPORT"],
        [context.report_label],
        [context.generated_at_label],
        [f"Total Rows: {context.total_rows}"],
        [],
        REPORT_HEADERS,
    ] + [row.as_list() for row in rows]
    shared_strings: list[str] = []
    string_index: dict[str, int] = {}

    def shared_string_id(value: str) -> int:
        if value not in string_index:
            string_index[value] = len(shared_strings)
            shared_strings.append(value)
        return string_index[value]

    def col_name(idx: int) -> str:
        chars = []
        n = idx
        while n:
            n, rem = divmod(n - 1, 26)
            chars.append(chr(65 + rem))
        return "".join(reversed(chars))

    row_xml_parts = []
    for row_idx, row in enumerate(sheet_rows, start=1):
        cells = []
        for col_idx, value in enumerate(row, start=1):
            cell_ref = f"{col_name(col_idx)}{row_idx}"
            style_id = "1" if row_idx in {1, 2, 3, 4, 6} else "0"
            if isinstance(value, int):
                cells.append(f'<c r="{cell_ref}" s="{style_id}"><v>{value}</v></c>')
            else:
                shared_id = shared_string_id(str(value))
                cells.append(f'<c r="{cell_ref}" t="s" s="{style_id}"><v>{shared_id}</v></c>')
        row_xml_parts.append(f'<row r="{row_idx}">{"".join(cells)}</row>')

    shared_xml = "".join(
        f"<si><t>{escape(text)}</t></si>"
        for text in shared_strings
    )
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'
        '<sheetFormatPr defaultRowHeight="18"/>'
        '<cols>'
        '<col min="1" max="1" width="22" customWidth="1"/>'
        '<col min="2" max="2" width="14" customWidth="1"/>'
        '<col min="3" max="3" width="12" customWidth="1"/>'
        '<col min="4" max="4" width="24" customWidth="1"/>'
        '<col min="5" max="10" width="16" customWidth="1"/>'
        '</cols>'
        f'<sheetData>{"".join(row_xml_parts)}</sheetData>'
        '<mergeCells count="4">'
        '<mergeCell ref="A1:J1"/>'
        '<mergeCell ref="A2:J2"/>'
        '<mergeCell ref="A3:J3"/>'
        '<mergeCell ref="A4:J4"/>'
        '</mergeCells>'
        '</worksheet>'
    )

    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Daily Report" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    )
    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
        '<Relationship Id="rId3" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" '
        'Target="sharedStrings.xml"/>'
        '</Relationships>'
    )
    root_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
        'Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" '
        'Target="docProps/app.xml"/>'
        '</Relationships>'
    )
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        '</Types>'
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2">'
        '<font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font>'
        '</fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        '</cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>'
    )
    core_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<dc:title>Daily Safety Alert Report</dc:title>'
        '<dc:creator>Axis CCTV</dc:creator>'
        f'<dc:description>{escape(context.report_label)}</dc:description>'
        '</cp:coreProperties>'
    )
    app_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        '<Application>Axis CCTV</Application>'
        '</Properties>'
    )

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", root_rels_xml)
        zf.writestr("docProps/core.xml", core_xml)
        zf.writestr("docProps/app.xml", app_xml)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        zf.writestr("xl/styles.xml", styles_xml)
        zf.writestr(
            "xl/sharedStrings.xml",
            (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                f'count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">{shared_xml}</sst>'
            ),
        )
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return output.getvalue()


def render_daily_report_pdf(
    rows: list[DailyReportRow],
    report_date: date,
    context: ReportRenderContext | None = None,
) -> bytes:
    context = context or build_report_context(report_date=report_date, total_rows=len(rows))
    title = "AXIS CCTV ALERT REPORT"
    summary = _build_report_summary(rows)
    table_rows = [[str(value) for value in row.as_list()] for row in rows]
    return _render_table_pdf(
        title=title,
        subtitle=context.report_label,
        metadata=[context.generated_at_label, f"Total Rows: {context.total_rows}"],
        summary=summary,
        headers=REPORT_HEADERS,
        rows=table_rows,
    )


def _build_report_summary(rows: list[DailyReportRow]) -> list[tuple[str, str]]:
    total_helmet = sum(row.without_helmet for row in rows)
    total_boot = sum(row.without_boot for row in rows)
    total_gloves = sum(row.without_gloves for row in rows)
    total_vest = sum(row.without_vest for row in rows)
    safe_zone_hits = sum(1 for row in rows if row.safe_zone == "YES")
    off_hours_hits = sum(1 for row in rows if row.off_hours == "YES")
    unique_cameras = len({row.camera_id for row in rows})
    return [
        ("Vest Alerts", str(total_vest)),
        ("Helmet Alerts", str(total_helmet)),
        ("Boot Alerts", str(total_boot)),
        ("Gloves Alerts", str(total_gloves)),
        ("Cameras Covered", str(unique_cameras)),
        ("Safe Zone Flags", str(safe_zone_hits)),
        ("Off Hours Flags", str(off_hours_hits)),
    ]


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap_pdf_text(text: str, width: int) -> list[str]:
    words = (text or "").split()
    if not words:
        return [""]
    lines = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if len(candidate) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _render_table_pdf(
    *,
    title: str,
    subtitle: str,
    metadata: list[str],
    summary: list[tuple[str, str]],
    headers: list[str],
    rows: list[list[str]],
) -> bytes:
    page_width = 842
    page_height = 595
    margin_x = 20
    top_margin = 36
    bottom_margin = 16
    content_width = page_width - (margin_x * 2)
    col_widths = [76, 56, 54, 108, 66, 64, 72, 66, 68, 68]
    table_width = sum(col_widths)
    table_x = margin_x
    x_positions = [margin_x]
    for width in col_widths:
        x_positions.append(x_positions[-1] + width)

    header_lines = [_wrap_pdf_text(header, max(8, math.floor((width - 10) / 5))) for header, width in zip(headers, col_widths)]
    header_height = max(len(lines) for lines in header_lines) * 11 + 12
    row_height = 20
    title_block_height = 182
    footer_height = 40
    page_label_height = 20
    first_page_table_top = page_height - top_margin - title_block_height
    other_page_table_top = page_height - top_margin - 8
    first_page_usable_height = first_page_table_top - bottom_margin - footer_height - page_label_height
    other_page_usable_height = other_page_table_top - bottom_margin - page_label_height
    first_page_rows_per_page = max(1, math.floor((first_page_usable_height - header_height) / row_height))
    other_page_rows_per_page = max(1, math.floor((other_page_usable_height - header_height) / row_height))

    page_streams: list[bytes] = []
    if not rows:
        rows = [["-", "-", "-", "No alerts found for this date.", "-", "-", "-", "-", "-", "-"]]

    page_slices: list[list[list[str]]] = []
    start = 0
    while start < len(rows):
        if not page_slices:
            page_size = first_page_rows_per_page
        else:
            page_size = other_page_rows_per_page
        page_slices.append(rows[start:start + page_size])
        start += page_size
    total_pages = max(1, len(page_slices))

    for page_index, page_rows in enumerate(page_slices):
        commands: list[str] = []

        def draw_text(x: float, y: float, text: str, *, font: str = "F1", size: int = 10) -> None:
            safe_text = _pdf_escape(text)
            commands.append(f"BT /{font} {size} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm ({safe_text}) Tj ET")

        def set_fill_color(r: float, g: float, b: float) -> None:
            commands.append(f"{r:.3f} {g:.3f} {b:.3f} rg")

        def set_stroke_color(r: float, g: float, b: float) -> None:
            commands.append(f"{r:.3f} {g:.3f} {b:.3f} RG")

        def draw_line(x1: float, y1: float, x2: float, y2: float, width: float = 1) -> None:
            commands.append(f"{width:.2f} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")

        def draw_rect(x: float, y: float, width: float, height: float, *, fill: bool = False) -> None:
            operator = "f" if fill else "S"
            commands.append(f"{x:.2f} {y:.2f} {width:.2f} {height:.2f} re {operator}")

        if page_index == 0:
            # Brand header only on first page
            set_fill_color(0.145, 0.180, 0.212)
            draw_rect(margin_x, page_height - top_margin - 50, content_width, 44, fill=True)
            set_fill_color(1.000, 0.522, 0.212)
            draw_rect(margin_x, page_height - top_margin - 50, 10, 44, fill=True)
            set_fill_color(1.000, 1.000, 1.000)
            draw_text(margin_x + 20, page_height - top_margin - 22, title, font="F2", size=18)
            set_fill_color(0.733, 0.749, 0.765)
            draw_text(margin_x + 20, page_height - top_margin - 38, subtitle, font="F1", size=9)
            draw_text(margin_x + 220, page_height - top_margin - 38, metadata[0], font="F1", size=9)
            draw_text(margin_x + 455, page_height - top_margin - 38, metadata[1], font="F1", size=9)

            brand_center_x = page_width - margin_x - 116
            set_fill_color(0.505, 0.545, 0.584)
            draw_text(brand_center_x, page_height - top_margin - 24, "AXIS", font="F2", size=22)

            set_stroke_color(1.000, 0.522, 0.212)
            draw_line(margin_x, page_height - top_margin - 58, page_width - margin_x, page_height - top_margin - 58, 1.4)

            # Summary strip only on first page
            summary_top = page_height - top_margin - 74
            summary_box_height = 54
            summary_gap = 8
            summary_items = summary[:4]
            summary_width = (content_width - (summary_gap * (len(summary_items) - 1))) / max(1, len(summary_items))
            for idx, (label, value) in enumerate(summary_items):
                box_x = margin_x + idx * (summary_width + summary_gap)
                set_fill_color(0.972, 0.976, 0.980)
                draw_rect(box_x, summary_top - summary_box_height, summary_width, summary_box_height, fill=True)
                set_stroke_color(0.875, 0.906, 0.933)
                draw_rect(box_x, summary_top - summary_box_height, summary_width, summary_box_height, fill=False)
                set_fill_color(1.000, 0.522, 0.212)
                draw_text(box_x + 10, summary_top - 18, value, font="F2", size=16)
                set_fill_color(0.255, 0.318, 0.373)
                draw_text(box_x + 10, summary_top - 34, label, font="F1", size=8)

            notes_top = summary_top - summary_box_height - 16
            notes_height = 28
            set_fill_color(0.925, 0.941, 0.957)
            draw_rect(margin_x, notes_top - notes_height, content_width, notes_height, fill=True)
            set_stroke_color(0.875, 0.906, 0.933)
            draw_rect(margin_x, notes_top - notes_height, content_width, notes_height, fill=False)
            set_fill_color(0.145, 0.180, 0.212)
            draw_text(margin_x + 10, notes_top - 18, "Quick Snapshot", font="F2", size=9)
            snapshot_text = (
                f"Cameras Covered: {summary[4][1]}   |   Safe Zone Flags: {summary[5][1]}   |   Off Hours Flags: {summary[6][1]}   |   Rows Included: {metadata[1].split(': ')[1]}"
            )
            draw_text(margin_x + 118, notes_top - 18, snapshot_text, font="F1", size=8)
            table_top = first_page_table_top
        else:
            table_top = other_page_table_top

        header_top = table_top
        header_bottom = header_top - header_height
        set_fill_color(0.925, 0.941, 0.957)
        draw_rect(table_x, header_bottom, table_width, header_height, fill=True)
        for idx, wrapped_lines in enumerate(header_lines):
            cell_x = x_positions[idx]
            for line_idx, line in enumerate(wrapped_lines):
                set_fill_color(0.145, 0.180, 0.212)
                draw_text(cell_x + 4, header_top - 15 - (line_idx * 11), line, font="F2", size=8)

        current_y = header_bottom
        for row_index, row in enumerate(page_rows):
            next_y = current_y - row_height
            if row_index % 2 == 0:
                set_fill_color(0.972, 0.976, 0.980)
                draw_rect(table_x, next_y, table_width, row_height, fill=True)
            for idx, value in enumerate(row):
                text = value
                max_chars = max(4, math.floor((col_widths[idx] - 8) / 5))
                if len(text) > max_chars:
                    text = text[: max_chars - 3] + "..."
                set_fill_color(0.125, 0.145, 0.165)
                draw_text(x_positions[idx] + 4, current_y - 13, text, font="F1", size=8)
            current_y = next_y

        bottom_y = current_y
        set_stroke_color(0.541, 0.592, 0.639)
        for x in x_positions:
            draw_line(x, header_top, x, bottom_y, 0.7)
        draw_line(x_positions[-1], header_top, x_positions[-1], bottom_y, 0.7)
        set_stroke_color(0.255, 0.318, 0.373)
        draw_line(table_x, header_top, table_x + table_width, header_top, 0.9)
        draw_line(table_x, header_bottom, table_x + table_width, header_bottom, 0.9)
        for line_idx in range(len(page_rows)):
            y = header_bottom - ((line_idx + 1) * row_height)
            draw_line(table_x, y, table_x + table_width, y, 0.5)

        set_fill_color(1.000, 0.522, 0.212)
        draw_text((page_width / 2) - 30, 18, f"Page {page_index + 1} of {total_pages}", font="F2", size=10)

        if page_index == total_pages - 1:
            # Footer only on last page
            footer_y = 2
            footer_h = 16
            set_fill_color(0.145, 0.180, 0.212)
            draw_rect(margin_x, footer_y, content_width, footer_h, fill=True)
            set_fill_color(1.000, 0.522, 0.212)
            draw_rect(margin_x, footer_y, 6, footer_h, fill=True)
            draw_rect(page_width - margin_x - 6, footer_y, 6, footer_h, fill=True)
            set_fill_color(1.000, 1.000, 1.000)
            draw_text(margin_x + 12, 8, "AXIS Solutions Limited", font="F2", size=8)
            draw_text(margin_x + 132, 8, "info@axisindia.in", font="F1", size=7)
            draw_text(margin_x + 250, 8, "+91 90990 6354", font="F1", size=7)
            draw_text(margin_x + 352, 8, "Ahmedabad, Gujarat, India", font="F1", size=7)
            set_fill_color(1.000, 0.522, 0.212)
            draw_text(page_width - margin_x - 178, 8, "AXIS CCTV Monitoring Export", font="F2", size=7)
        page_streams.append("\n".join(commands).encode("latin-1", errors="replace"))

    return _build_pdf_document(page_width, page_height, page_streams)


def _build_pdf_document(page_width: int, page_height: int, page_streams: list[bytes]) -> bytes:
    objects: list[bytes] = []

    def add_object(data: str | bytes) -> int:
        payload = data.encode("latin-1") if isinstance(data, str) else data
        objects.append(payload)
        return len(objects)

    font_regular_id = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    font_bold_id = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

    content_ids = []
    page_ids = []
    for stream in page_streams:
        content_id = add_object(
            b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream"
        )
        content_ids.append(content_id)
        page_ids.append(add_object(""))

    pages_id = add_object("")
    for page_id, content_id in zip(page_ids, content_ids):
        objects[page_id - 1] = (
            f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {page_width} {page_height}] "
            f"/Resources << /Font << /F1 {font_regular_id} 0 R /F2 {font_bold_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode("latin-1")

    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[pages_id - 1] = f"<< /Type /Pages /Count {len(page_ids)} /Kids [{kids}] >>".encode("latin-1")
    catalog_id = add_object(f"<< /Type /Catalog /Pages {pages_id} 0 R >>")

    output = io.BytesIO()
    output.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for idx, payload in enumerate(objects, start=1):
        offsets.append(output.tell())
        output.write(f"{idx} 0 obj\n".encode("ascii"))
        output.write(payload)
        output.write(b"\nendobj\n")
    xref_offset = output.tell()
    output.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.write(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF"
        ).encode("ascii")
    )
    return output.getvalue()


def save_report_artifacts(
    rows: list[DailyReportRow],
    report_date: date,
    output_dir: str | Path,
    context: ReportRenderContext | None = None,
) -> dict[str, Path]:
    context = context or build_report_context(report_date=report_date, total_rows=len(rows))
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    pdf_path = directory / build_report_filename(context.filename_date_label, "pdf")
    xlsx_path = directory / build_report_filename(context.filename_date_label, "xlsx")
    pdf_path.write_bytes(render_daily_report_pdf(rows, report_date, context))
    xlsx_path.write_bytes(render_daily_report_xlsx(rows, report_date, context))
    return {"pdf": pdf_path, "xlsx": xlsx_path}


def get_daily_alerts_query(db, report_date: date):
    start_dt, end_dt = _report_window(report_date)
    return (
        db.query(Alert)
        .filter(Alert.triggered_at >= start_dt)
        .filter(Alert.triggered_at < end_dt)
        .order_by(Alert.triggered_at.asc(), Alert.camera_id.asc(), Alert.id.asc())
    )
