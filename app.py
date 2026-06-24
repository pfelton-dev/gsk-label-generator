import json
import math
import re
from datetime import datetime
from pathlib import Path
from io import BytesIO

import streamlit as st
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase.pdfmetrics import stringWidth


APP_TITLE = "Sterling Label Generator v1.2"
FOOTER_TEXT = "Sterling NA, Hauppauge NY"
SAVED_JOBS_DIR = Path("saved_jobs")

# Avery 5163 / 2" x 4" labels, 10 per letter sheet.
PAGE_WIDTH, PAGE_HEIGHT = letter
LABEL_WIDTH = 4.0 * 72
LABEL_HEIGHT = 2.0 * 72
LEFT_MARGIN = 0.1625 * 72
TOP_MARGIN = 0.50 * 72
H_GAP = 0.175 * 72
V_GAP = 0.0 * 72

DEFAULT_FONT = "Helvetica"
DEFAULT_FONT_SIZE = 12
MIN_FONT_SIZE = 7


def clean_filename(value: str) -> str:
    value = value.strip() or "saved_job"
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value)[:80]


def calculate_cartons(total_qty: int, qty_per_full_box: int):
    if qty_per_full_box <= 0:
        return 0, 0, 0
    full_boxes = total_qty // qty_per_full_box
    partial_qty = total_qty % qty_per_full_box
    total_boxes = full_boxes + (1 if partial_qty else 0)
    return full_boxes, partial_qty, total_boxes


def partial_pack_breakdown(partial_qty: int, pieces_per_pack: int):
    if partial_qty <= 0 or pieces_per_pack <= 0:
        return ""

    full_packs = partial_qty // pieces_per_pack
    leftover = partial_qty % pieces_per_pack

    parts = []
    if full_packs:
        pack_word = "PACK" if full_packs == 1 else "PACKS"
        parts.append(f"{full_packs} {pack_word} OF {pieces_per_pack}")
    if leftover:
        parts.append(f"1 PACK OF {leftover}")

    return " + ".join(parts)


def wrap_line(text, max_width, font_name, font_size):
    words = str(text).split()
    if not words:
        return [""]

    lines = []
    current = ""

    for word in words:
        test = word if not current else f"{current} {word}"
        if stringWidth(test, font_name, font_size) <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines


def fit_label_lines(raw_lines, max_width, max_height):
    font_size = DEFAULT_FONT_SIZE

    while font_size >= MIN_FONT_SIZE:
        wrapped = []
        for raw in raw_lines:
            wrapped.extend(wrap_line(raw, max_width, DEFAULT_FONT, font_size))

        line_height = font_size * 1.12
        total_height = len(wrapped) * line_height

        if total_height <= max_height:
            return wrapped, font_size, line_height

        font_size -= 1

    wrapped = []
    for raw in raw_lines:
        wrapped.extend(wrap_line(raw, max_width, DEFAULT_FONT, MIN_FONT_SIZE))
    return wrapped, MIN_FONT_SIZE, MIN_FONT_SIZE * 1.12


def build_mdc_label_lines(gmm, wmn, description, pcs_qty, carton_num, total_cartons, is_partial):
    lines = []

    if is_partial:
        lines.append("_____ PARTIAL _____")

    lines.append(f"GMM# {gmm}".strip())
    lines.append(f"WMN# {wmn}".strip())

    for line in str(description).splitlines():
        cleaned = line.strip()
        if cleaned:
            lines.append(cleaned)

    lines.append(f"{pcs_qty:,} PCS")
    lines.append(FOOTER_TEXT)
    lines.append(f"Carton {carton_num} of {total_cartons}")

    return lines


def build_non_mdc_label_lines(destination, description, fold_size, qty_for_box, pack_of_per_full_box,
                              pieces_per_pack, carton_num, total_cartons, is_partial):
    lines = []

    if is_partial:
        lines.append("_____ PARTIAL _____")

    for item in [destination, description, fold_size]:
        for line in str(item).splitlines():
            cleaned = line.strip()
            if cleaned:
                lines.append(cleaned)

    if is_partial:
        lines.append(f"{qty_for_box:,} QTY")
        breakdown = partial_pack_breakdown(qty_for_box, pieces_per_pack)
        if breakdown:
            lines.append(breakdown)
    else:
        lines.append(f"{pack_of_per_full_box:,} PACKS OF {pieces_per_pack:,}")

    lines.append(FOOTER_TEXT)
    lines.append(f"Carton {carton_num} of {total_cartons}")

    return lines


def parse_print_selection(mode, selection_text, total_cartons):
    if total_cartons <= 0:
        return []

    if mode == "Full Job":
        return list(range(1, total_cartons + 1))

    selection_text = selection_text.strip()

    if mode == "Single Carton":
        if not selection_text.isdigit():
            raise ValueError("Enter one carton number.")
        cartons = [int(selection_text)]

    elif mode == "Carton Range":
        match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", selection_text)
        if not match:
            raise ValueError("Enter a range like 5-10.")
        start, end = int(match.group(1)), int(match.group(2))
        if start > end:
            raise ValueError("Range start cannot be greater than range end.")
        cartons = list(range(start, end + 1))

    else:
        parts = [p.strip() for p in selection_text.split(",") if p.strip()]
        if not parts or not all(p.isdigit() for p in parts):
            raise ValueError("Enter missing labels like 2,7,11,16.")
        cartons = [int(p) for p in parts]

    bad = [c for c in cartons if c < 1 or c > total_cartons]
    if bad:
        raise ValueError(f"Carton number out of range: {bad[0]}. Valid range is 1-{total_cartons}.")

    seen = set()
    unique = []
    for c in cartons:
        if c not in seen:
            unique.append(c)
            seen.add(c)
    return unique


def label_position(index_zero_based):
    position = index_zero_based % 10
    col = position % 2
    row = position // 2

    x = LEFT_MARGIN + col * (LABEL_WIDTH + H_GAP)
    y = PAGE_HEIGHT - TOP_MARGIN - LABEL_HEIGHT - row * (LABEL_HEIGHT + V_GAP)
    return x, y


def draw_label(c, x, y, lines):
    padding_x = 0.16 * 72
    padding_y = 0.13 * 72

    max_text_width = LABEL_WIDTH - 2 * padding_x
    max_text_height = LABEL_HEIGHT - 2 * padding_y

    fitted_lines, font_size, line_height = fit_label_lines(lines, max_text_width, max_text_height)

    c.setFont(DEFAULT_FONT, font_size)

    total_text_height = len(fitted_lines) * line_height
    start_y = y + (LABEL_HEIGHT + total_text_height) / 2 - line_height

    for i, line in enumerate(fitted_lines):
        text_y = start_y - i * line_height
        text_x = x + LABEL_WIDTH / 2
        c.drawCentredString(text_x, text_y, line)


def create_pdf(label_type, job_data, cartons_to_print, start_position):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)

    blanks = start_position - 1
    slot_index = 0

    if label_type == "MDC":
        full_boxes, partial_qty, total_cartons = calculate_cartons(
            int(job_data["total_pieces"]), int(job_data["pieces_per_box"])
        )
    else:
        full_boxes, partial_qty, total_cartons = calculate_cartons(
            int(job_data["total_qty"]), int(job_data["qty_per_full_box"])
        )

    for carton_num in cartons_to_print:
        if slot_index > 0 and (slot_index + blanks) % 10 == 0:
            c.showPage()

        page_slot = slot_index + blanks
        x, y = label_position(page_slot)

        is_partial = partial_qty > 0 and carton_num == total_cartons

        if label_type == "MDC":
            pcs_qty = partial_qty if is_partial else int(job_data["pieces_per_box"])
            lines = build_mdc_label_lines(
                gmm=job_data["gmm"],
                wmn=job_data["wmn"],
                description=job_data["description"],
                pcs_qty=pcs_qty,
                carton_num=carton_num,
                total_cartons=total_cartons,
                is_partial=is_partial,
            )
        else:
            qty_for_box = partial_qty if is_partial else int(job_data["qty_per_full_box"])
            lines = build_non_mdc_label_lines(
                destination=job_data["destination"],
                description=job_data["description"],
                fold_size=job_data["fold_size"],
                qty_for_box=qty_for_box,
                pack_of_per_full_box=int(job_data["pack_of_per_full_box"]),
                pieces_per_pack=int(job_data["pieces_per_pack"]),
                carton_num=carton_num,
                total_cartons=total_cartons,
                is_partial=is_partial,
            )

        draw_label(c, x, y, lines)
        slot_index += 1

    c.save()
    buffer.seek(0)
    return buffer.getvalue()


def save_job(job):
    SAVED_JOBS_DIR.mkdir(exist_ok=True)
    filename_base = clean_filename(f"{job.get('label_type', '')}_{job.get('job_number') or job.get('description', 'saved_job')}")
    path = SAVED_JOBS_DIR / f"{filename_base}.json"

    if path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = SAVED_JOBS_DIR / f"{filename_base}_{timestamp}.json"

    path.write_text(json.dumps(job, indent=2), encoding="utf-8")
    return path


def load_jobs():
    SAVED_JOBS_DIR.mkdir(exist_ok=True)
    jobs = []
    for path in sorted(SAVED_JOBS_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["_path"] = str(path)
            jobs.append(data)
        except Exception:
            continue
    return jobs


def apply_loaded_job(job):
    st.session_state["label_type"] = job.get("label_type", "MDC")
    st.session_state["job_number"] = job.get("job_number", "")
    st.session_state["description"] = job.get("description", "")

    if job.get("label_type") == "Non-MDC":
        st.session_state["destination"] = job.get("destination", "")
        st.session_state["fold_size"] = job.get("fold_size", "")
        st.session_state["total_qty"] = int(job.get("total_qty", 0) or 0)
        st.session_state["qty_per_full_box"] = int(job.get("qty_per_full_box", 0) or 0)
        st.session_state["pack_of_per_full_box"] = int(job.get("pack_of_per_full_box", 0) or 0)
        st.session_state["pieces_per_pack"] = int(job.get("pieces_per_pack", 0) or 0)
    else:
        st.session_state["gmm"] = job.get("gmm", "")
        st.session_state["wmn"] = job.get("wmn", "")
        st.session_state["total_pieces"] = int(job.get("total_pieces", 0) or 0)
        st.session_state["pieces_per_box"] = int(job.get("pieces_per_box", 0) or 0)


st.set_page_config(page_title=APP_TITLE, layout="wide")
st.title(APP_TITLE)

with st.sidebar:
    st.header("Saved Jobs")
    search = st.text_input("Search by Job # or Description")

    jobs = load_jobs()
    if search:
        s = search.lower()
        jobs = [
            j for j in jobs
            if s in str(j.get("job_number", "")).lower()
            or s in str(j.get("description", "")).lower()
            or s in str(j.get("gmm", "")).lower()
            or s in str(j.get("wmn", "")).lower()
            or s in str(j.get("destination", "")).lower()
        ]

    if jobs:
        labels = []
        for j in jobs[:50]:
            first_desc = str(j.get("description", "")).splitlines()[0] if j.get("description") else ""
            labels.append(f"{j.get('label_type', 'MDC')} | {j.get('job_number', 'No Job #')} - {first_desc}")

        selected = st.selectbox("Saved job results", labels)
        selected_job = jobs[labels.index(selected)]

        if st.button("Load Selected Job"):
            apply_loaded_job(selected_job)
            st.rerun()
    else:
        st.caption("No saved jobs found yet.")


left, right = st.columns([1.2, 1])

with left:
    st.subheader("Label Type")
    label_type = st.selectbox("Label Type", ["MDC", "Non-MDC"], key="label_type")

    st.subheader("Job Information")
    job_number = st.text_input("Job # (for saving/tracking only - does not print)", key="job_number")

    if label_type == "MDC":
        gmm = st.text_input("GMM#", key="gmm")
        wmn = st.text_input("WMN#", key="wmn")
        description = st.text_area("Description", height=110, key="description")

        st.subheader("Packing Information")
        col1, col2 = st.columns(2)
        with col1:
            total_pieces = st.number_input("Total Pieces", min_value=0, step=1, key="total_pieces")
        with col2:
            pieces_per_box = st.number_input("Pieces Per Box", min_value=0, step=1, key="pieces_per_box")

        full_boxes, partial_qty, total_cartons = calculate_cartons(int(total_pieces), int(pieces_per_box))

        job_data = {
            "label_type": label_type,
            "job_number": job_number.strip(),
            "gmm": gmm.strip(),
            "wmn": wmn.strip(),
            "description": description.strip(),
            "total_pieces": int(total_pieces),
            "pieces_per_box": int(pieces_per_box),
        }

    else:
        destination = st.text_area("Destination", height=70, key="destination")
        description = st.text_area("Description", height=90, key="description")
        fold_size = st.text_input("Fold / Size", key="fold_size")

        st.subheader("Packing Information")
        col1, col2 = st.columns(2)
        with col1:
            total_qty = st.number_input("Total Qty", min_value=0, step=1, key="total_qty")
            pack_of_per_full_box = st.number_input("Pack Of # Per Full Box", min_value=0, step=1, key="pack_of_per_full_box")
        with col2:
            qty_per_full_box = st.number_input("Qty Per Full Box", min_value=0, step=1, key="qty_per_full_box")
            pieces_per_pack = st.number_input("Pieces Per Pack", min_value=0, step=1, key="pieces_per_pack")

        full_boxes, partial_qty, total_cartons = calculate_cartons(int(total_qty), int(qty_per_full_box))
        partial_breakdown = partial_pack_breakdown(int(partial_qty), int(pieces_per_pack))

        job_data = {
            "label_type": label_type,
            "job_number": job_number.strip(),
            "destination": destination.strip(),
            "description": description.strip(),
            "fold_size": fold_size.strip(),
            "total_qty": int(total_qty),
            "qty_per_full_box": int(qty_per_full_box),
            "pack_of_per_full_box": int(pack_of_per_full_box),
            "pieces_per_pack": int(pieces_per_pack),
        }

    st.subheader("Print Options")
    print_mode = st.radio(
        "Print Mode",
        ["Full Job", "Single Carton", "Carton Range", "Missing Labels"],
        horizontal=True
    )

    selection_text = ""
    if print_mode == "Single Carton":
        selection_text = st.text_input("Carton number", placeholder="7")
    elif print_mode == "Carton Range":
        selection_text = st.text_input("Carton range", placeholder="5-10")
    elif print_mode == "Missing Labels":
        selection_text = st.text_input("Missing labels", placeholder="2,7,11,16")

    start_position = st.selectbox("Starting Label Position", list(range(1, 11)), index=0)

with right:
    st.subheader("Summary")

    if label_type == "MDC":
        st.write(f"**Total Pieces:** {int(total_pieces):,}")
        st.write(f"**Pieces Per Box:** {int(pieces_per_box):,}" if pieces_per_box else "**Pieces Per Box:** 0")
        st.write(f"**Full Boxes:** {full_boxes:,}")
        st.write(f"**Partial Box Qty:** {partial_qty:,}")
        st.write(f"**Total Boxes Needed:** {total_cartons:,}")
    else:
        st.write(f"**Total Qty:** {int(total_qty):,}")
        st.write(f"**Qty Per Full Box:** {int(qty_per_full_box):,}")
        st.write(f"**Pack Of # Per Full Box:** {int(pack_of_per_full_box):,}")
        st.write(f"**Pieces Per Pack:** {int(pieces_per_pack):,}")
        st.write(f"**Full Boxes:** {full_boxes:,}")
        st.write(f"**Partial Qty:** {partial_qty:,}")
        st.write(f"**Partial Packs:** {partial_breakdown or 'None'}")
        st.write(f"**Total Boxes Needed:** {total_cartons:,}")

    try:
        cartons_to_print = parse_print_selection(print_mode, selection_text, total_cartons)
        labels_to_print = len(cartons_to_print)
        sheets_required = math.ceil((labels_to_print + int(start_position) - 1) / 10) if labels_to_print else 0
        st.write(f"**Labels To Print:** {labels_to_print:,}")
        st.write(f"**Avery Sheets Required:** {sheets_required:,}")
    except Exception as e:
        cartons_to_print = []
        st.warning(str(e))

    st.subheader("Label Preview")

    if total_cartons > 0:
        preview_carton = total_cartons if partial_qty else 1
        preview_is_partial = partial_qty > 0 and preview_carton == total_cartons

        if label_type == "MDC":
            preview_qty = partial_qty if preview_is_partial else int(pieces_per_box)
            preview_lines = build_mdc_label_lines(
                gmm=gmm or "2005108616",
                wmn=wmn or "0002-0045-49",
                description=description or "BLUJEPA PI GPT_750MG_v3 Update\nMarch 2026",
                pcs_qty=preview_qty,
                carton_num=preview_carton,
                total_cartons=total_cartons,
                is_partial=preview_is_partial,
            )
        else:
            preview_qty = partial_qty if preview_is_partial else int(qty_per_full_box)
            preview_lines = build_non_mdc_label_lines(
                destination=destination or "HEALTH MONITOR - QUAD",
                description=description or "PM-US-GPT-DPB-250001 Blujepa Wallboards- JULY- PIs",
                fold_size=fold_size or "1/4-FOLD TO 4.1875X5.4375",
                qty_for_box=preview_qty,
                pack_of_per_full_box=int(pack_of_per_full_box) if pack_of_per_full_box else 200,
                pieces_per_pack=int(pieces_per_pack) if pieces_per_pack else 6,
                carton_num=preview_carton,
                total_cartons=total_cartons,
                is_partial=preview_is_partial,
            )

        st.code("\n".join(preview_lines), language="text")
    else:
        st.caption("Enter packing information to preview label.")

st.divider()

save_col, pdf_col = st.columns(2)

with save_col:
    if st.button("Save Job"):
        if not job_number.strip():
            st.error("Enter a Job # before saving.")
        elif label_type == "MDC":
            if not job_data["gmm"] or not job_data["wmn"] or not job_data["description"]:
                st.error("GMM#, WMN#, and Description are required.")
            elif job_data["total_pieces"] <= 0 or job_data["pieces_per_box"] <= 0:
                st.error("Total Pieces and Pieces Per Box must be greater than 0.")
            else:
                job_data["saved_at"] = datetime.now().isoformat(timespec="seconds")
                saved_path = save_job(job_data)
                st.success(f"Saved: {saved_path.name}")
        else:
            if not job_data["destination"] or not job_data["description"] or not job_data["fold_size"]:
                st.error("Destination, Description, and Fold / Size are required.")
            elif job_data["total_qty"] <= 0 or job_data["qty_per_full_box"] <= 0 or job_data["pack_of_per_full_box"] <= 0 or job_data["pieces_per_pack"] <= 0:
                st.error("All packing fields must be greater than 0.")
            else:
                job_data["saved_at"] = datetime.now().isoformat(timespec="seconds")
                saved_path = save_job(job_data)
                st.success(f"Saved: {saved_path.name}")

with pdf_col:
    generate = st.button("Generate PDF", type="primary")

    if generate:
        if label_type == "MDC":
            valid = job_data["gmm"] and job_data["wmn"] and job_data["description"] and job_data["total_pieces"] > 0 and job_data["pieces_per_box"] > 0
            error_msg = "GMM#, WMN#, Description, Total Pieces, and Pieces Per Box are required."
        else:
            valid = (
                job_data["destination"] and job_data["description"] and job_data["fold_size"]
                and job_data["total_qty"] > 0 and job_data["qty_per_full_box"] > 0
                and job_data["pack_of_per_full_box"] > 0 and job_data["pieces_per_pack"] > 0
            )
            error_msg = "Destination, Description, Fold / Size, and all packing fields are required."

        if not valid:
            st.error(error_msg)
        elif not cartons_to_print:
            st.error("No labels selected to print.")
        else:
            pdf_bytes = create_pdf(
                label_type=label_type,
                job_data=job_data,
                cartons_to_print=cartons_to_print,
                start_position=int(start_position),
            )

            default_name = clean_filename(job_number or "labels")
            st.download_button(
                label="Download Label PDF",
                data=pdf_bytes,
                file_name=f"{default_name}_{clean_filename(label_type)}_labels.pdf",
                mime="application/pdf",
            )

st.caption("Tip: Print the PDF at 100% / Actual Size. Do not use Fit to Page.")
