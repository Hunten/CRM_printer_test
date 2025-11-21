import streamlit as st
import pandas as pd
from datetime import datetime, date
import io
import hashlib
import math
from pathlib import Path
from streamlit_gsheets import GSheetsConnection

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from PIL import Image
import json  # For multiple printers JSON
from typing import Optional


# ============================================================================
# APP CONFIG
# ============================================================================
st.set_page_config(
    page_title="PRINTHEAD Complete Solutions CRM",
    page_icon="🖨️",
    layout="wide",
)

# Load logo from repository - FIX: Keep as BytesIO
if "logo_image" not in st.session_state:
    try:
        logo_path = Path("logo.png")
        if logo_path.exists():
            with open(logo_path, "rb") as f:
                logo_bytes = f.read()
            st.session_state["logo_image"] = io.BytesIO(logo_bytes)
        else:
            st.session_state["logo_image"] = None
    except Exception as e:
        st.warning(f"Logo not found: {e}")
        st.session_state["logo_image"] = None

# Initialize session state
if "active_tab" not in st.session_state:
    st.session_state["active_tab"] = 0

if "last_tab" not in st.session_state:
    st.session_state["last_tab"] = 0

if "selected_order_for_update" not in st.session_state:
    st.session_state["selected_order_for_update"] = None

if "previous_selected_order" not in st.session_state:
    st.session_state["previous_selected_order"] = None

if "last_created_order" not in st.session_state:
    st.session_state["last_created_order"] = None

if "pdf_downloaded" not in st.session_state:
    st.session_state["pdf_downloaded"] = False

# For new-order temporary printers
if "temp_printers" not in st.session_state:
    st.session_state["temp_printers"] = [{"brand": "", "model": "", "serial": ""}]


# ============================================================================
# AUTHENTICATION
# ============================================================================
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def check_password() -> bool:
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    if st.session_state["authenticated"]:
        return True

    st.markdown("## 🔒 Login Required")
    st.markdown("Please enter your credentials to access the CRM system.")

    with st.form("login_form"):
        username = st.text_input("Username", value="admin")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login")

        if submit:
            try:
                correct_password = st.secrets["passwords"]["admin_password"]
            except KeyError:
                st.error("❌ Password not configured in secrets!")
                st.info("Add 'passwords.admin_password' in Streamlit Cloud Settings → Secrets")
                return False

            if username == "admin" and hash_password(password) == hash_password(correct_password):
                st.session_state["authenticated"] = True
                st.session_state["username"] = username
                st.success("✅ Login successful!")
                st.rerun()
            else:
                st.error("❌ Invalid username or password")

    return False


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================
def remove_diacritics(text):
    if not isinstance(text, str):
        return text
    diacritics_map = {
        "ă": "a", "Ă": "A", "â": "a", "Â": "A",
        "î": "i", "Î": "I", "ș": "s", "Ș": "S",
        "ț": "t", "Ț": "T",
    }
    for d, r in diacritics_map.items():
        text = text.replace(d, r)
    return text


def safe_text(value: object) -> str:
    """Transformă None / NaN în string gol, altfel în string normal."""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value)


def safe_float(value: object, default: float = 0.0) -> float:
    """Transformă None / NaN / string gol în 0 (sau default)."""
    try:
        if value is None:
            return default
        if isinstance(value, float) and math.isnan(value):
            return default
        if isinstance(value, str) and value.strip() == "":
            return default
        return float(value)
    except Exception:
        return default


def load_printers_from_order(order: dict):
    """
    Returnează o listă de imprimante din order:
    - încearcă printers_json
    - dacă e gol, folosește printer_brand/model/serial legacy
    """
    printers = []
    raw = safe_text(order.get("printers_json", "")).strip()
    if raw:
        try:
            printers = json.loads(raw)
        except Exception:
            printers = []

    if not printers:
        # fallback la campurile vechi
        brand = safe_text(order.get("printer_brand", "")).strip()
        model = safe_text(order.get("printer_model", "")).strip()
        serial = safe_text(order.get("printer_serial", "")).strip()
        if brand or model or serial:
            printers = [{
                "brand": brand,
                "model": model,
                "serial": serial
            }]
    # asigura structura
    cleaned = []
    for p in printers:
        cleaned.append({
            "brand": safe_text(p.get("brand", "")),
            "model": safe_text(p.get("model", "")),
            "serial": safe_text(p.get("serial", "")),
        })
    return cleaned


# ============================================================================
# GOOGLE SHEETS CONNECTION
# ============================================================================
@st.cache_resource
def get_sheets_connection():
    """Native Streamlit connection to Google Sheets using streamlit-gsheets."""
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        return conn
    except Exception as e:
        st.error(f"Google Sheets connection failed: {e}")
        return None


# ============================================================================
# PDF GENERATION - INITIAL RECEIPT (BON PREDARE)
# ============================================================================
def generate_initial_receipt_pdf(order, company_info, logo_image=None):
    """Generate PDF with HIGH QUALITY logo from repository - FIX parameter name"""
    buffer = io.BytesIO()
    width, height = 210*mm, 148.5*mm
    c = canvas.Canvas(buffer, pagesize=(width, height))

    # Logo cu calitate maximă - FIX: use logo_image not logo_buffer
    header_y_start = height-10*mm
    x_business = 10*mm
    y_pos = header_y_start

    # Company info - left side
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x_business, y_pos, remove_diacritics(company_info.get('company_name','')))
    y_pos -= 3.5*mm
    c.setFont("Helvetica", 7)
    c.drawString(x_business, y_pos, remove_diacritics(company_info.get('company_address','')))
    y_pos -= 3*mm
    c.drawString(x_business, y_pos, f"CUI: {company_info.get('cui','')}")
    y_pos -= 3*mm
    c.drawString(x_business, y_pos, f"Reg.Com: {company_info.get('reg_com','')}")
    y_pos -= 3*mm
    c.drawString(x_business, y_pos, f"Tel: {company_info.get('phone','')}")
    y_pos -= 3*mm
    c.drawString(x_business, y_pos, f"Email: {company_info.get('email','')}")

    # Logo middle
    logo_x = 85*mm
    logo_y = header_y_start-20*mm

    if logo_image:
        try:
            logo_image.seek(0)
            img = Image.open(logo_image)

            target_width_mm = 40
            aspect_ratio = img.height / img.width
            target_height_mm = target_width_mm * aspect_ratio

            if target_height_mm > 25:
                target_height_mm = 25
                target_width_mm = target_height_mm / aspect_ratio

            logo_image.seek(0)
            c.drawImage(
                ImageReader(logo_image),
                logo_x,
                logo_y,
                width=target_width_mm*mm,
                height=target_height_mm*mm,
                preserveAspectRatio=True,
                mask='auto'
            )
        except Exception:
            c.setFillColor(colors.HexColor('#f0f0f0'))
            c.rect(logo_x, logo_y, 40*mm, 25*mm, fill=1, stroke=1)
            c.setFillColor(colors.black)
            c.setFont("Helvetica-Bold", 10)
            c.drawCentredString(logo_x+20*mm, logo_y+12.5*mm, "[LOGO]")
    else:
        c.setFillColor(colors.HexColor('#f0f0f0'))
        c.rect(logo_x, logo_y, 40*mm, 25*mm, fill=1, stroke=1)
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(logo_x+20*mm, logo_y+12.5*mm, "[LOGO]")

    # Client info - right side
    c.setFillColor(colors.black)
    x_client = 155*mm
    y_pos = header_y_start
    c.setFont("Helvetica-Bold", 8)
    c.drawString(x_client, y_pos, "CLIENT")
    y_pos -= 3.5*mm
    c.setFont("Helvetica", 7)
    c.drawString(x_client, y_pos, f"Nume: {remove_diacritics(safe_text(order.get('client_name','')))}")
    y_pos -= 3*mm
    c.drawString(x_client, y_pos, f"Tel: {safe_text(order.get('client_phone',''))}")

    # Title
    title_y = height-38*mm
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(105*mm, title_y, "DOVADA PREDARE ECHIPAMENT IN SERVICE")
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(colors.HexColor('#E5283A'))
    c.drawCentredString(105*mm, title_y-6*mm, f"Nr. Comanda: {safe_text(order.get('order_id',''))}")
    c.setFillColor(colors.black)

    # Equipment details (MULTIPLE PRINTERS)
    y_pos = height-50*mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(10*mm, y_pos, "DETALII ECHIPAMENT:")
    y_pos -= 5*mm
    c.setFont("Helvetica", 8)

    printers = load_printers_from_order(order)

    if printers:
        for idx, p in enumerate(printers, start=1):
            brand = remove_diacritics(safe_text(p.get("brand", "")))
            model = remove_diacritics(safe_text(p.get("model", "")))
            serial = safe_text(p.get("serial", ""))

            line = f"{idx}. {brand} {model}"
            if serial:
                line += f" (SN: {serial})"

            c.drawString(10*mm, y_pos, line)
            y_pos -= 4*mm
    else:
        # fallback daca totusi nu exista nicio imprimanta
        printer_info = f"{remove_diacritics(safe_text(order.get('printer_brand','')))} {remove_diacritics(safe_text(order.get('printer_model','')))}"
        c.drawString(10*mm, y_pos, f"Imprimanta: {printer_info}")
        y_pos -= 4*mm
        serial = safe_text(order.get('printer_serial',''))
        if serial:
            c.drawString(10*mm, y_pos, f"Serie: {serial}")
            y_pos -= 4*mm

    # Data si accesorii - la nivel de comanda
    c.drawString(10*mm, y_pos, f"Data predarii: {safe_text(order.get('date_received',''))}")
    y_pos -= 4*mm

    accessories = safe_text(order.get('accessories',''))
    if accessories and accessories.strip():
        c.drawString(10*mm, y_pos, f"Accesorii: {remove_diacritics(accessories)}")
        y_pos -= 4*mm

    # Issue description
    y_pos -= 2*mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(10*mm, y_pos, "PROBLEMA RAPORTATA:")
    y_pos -= 4*mm
    c.setFont("Helvetica", 8)

    issue_text = remove_diacritics(safe_text(order.get('issue_description','')))
    text_object = c.beginText(10*mm, y_pos)
    text_object.setFont("Helvetica", 8)
    words = issue_text.split()
    line = ""
    for word in words:
        test_line = line + word + " "
        if c.stringWidth(test_line, "Helvetica", 8) < 190*mm:
            line = test_line
        else:
            text_object.textLine(line)
            line = word + " "
    if line:
        text_object.textLine(line)
    c.drawText(text_object)

    # Signature boxes
    sig_y = 22*mm
    sig_height = 18*mm

    c.rect(10*mm, sig_y, 85*mm, sig_height)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(12*mm, sig_y+sig_height-3*mm, "OPERATOR SERVICE")
    c.setFont("Helvetica", 7)
    c.drawString(12*mm, sig_y+2*mm, "Semnatura")

    c.rect(115*mm, sig_y, 85*mm, sig_height)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(117*mm, sig_y+sig_height-3*mm, "CLIENT")
    c.setFont("Helvetica", 7)
    c.drawString(117*mm, sig_y+sig_height-7*mm, "Am luat la cunostinta")
    c.drawString(117*mm, sig_y+2*mm, "Semnatura")

    #more info
    c.setFont("Helvetica-Bold", 7)
    c.drawCentredString(105*mm, 18*mm, "Avand in vedere ca dispozitivele din prezenta fisa nu au putut fi testate in momentul preluarii lor, acestea sunt considerate ca fiind nefunctionale.")
    c.setFont("Helvetica", 7)
    c.drawCentredString(105*mm, 15*mm, "Aveti obligatia ca, la finalizarea reparatiei echipamentului aflat in service, sa va prezentati in termen de 30 de zile de la data anuntarii de catre")
    c.setFont("Helvetica", 7)
    c.drawCentredString(105*mm, 12*mm, "reprezentantul SC PRINTHEAD COMPLETE SOLUTIONS SRL pentru a ridica echipamentul.In cazul neridicarii echipamentului")
    c.setFont("Helvetica", 7)
    c.drawCentredString(105*mm, 9*mm, "in intervalul specificat mai sus, ne rezervam dreptul de valorificare a acestuia")

    # Footer
    c.setFont("Helvetica", 6)
    c.drawCentredString(105*mm, 3*mm, "Acest document constituie dovada predarii echipamentului in service.")
    c.setDash(3, 3)
    c.line(5*mm, 1*mm, 205*mm, 1*mm)

    c.save()
    buffer.seek(0)
    return buffer


# ============================================================================
# PDF GENERATION - COMPLETION RECEIPT (3-COLUMN LAYOUT)
# ============================================================================
def generate_completion_receipt_pdf(order, company_info, logo_image=None):
    """Generate completion PDF with HIGH QUALITY logo - FIX parameter name"""
    buffer = io.BytesIO()
    width, height = 210*mm, 148.5*mm
    c = canvas.Canvas(buffer, pagesize=(width, height))

    header_y_start = height-10*mm
    x_business = 10*mm
    y_pos = header_y_start

    # Company info - left side
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x_business, y_pos, remove_diacritics(company_info.get('company_name','')))
    y_pos -= 3.5*mm
    c.setFont("Helvetica", 7)
    c.drawString(x_business, y_pos, remove_diacritics(company_info.get('company_address','')))
    y_pos -= 3*mm
    c.drawString(x_business, y_pos, f"CUI: {company_info.get('cui','')}")
    y_pos -= 3*mm
    c.drawString(x_business, y_pos, f"Reg.Com: {company_info.get('reg_com','')}")
    y_pos -= 3*mm
    c.drawString(x_business, y_pos, f"Tel: {company_info.get('phone','')}")
    y_pos -= 3*mm
    c.drawString(x_business, y_pos, f"Email: {company_info.get('email','')}")

    # Logo middle
    logo_x = 85*mm
    logo_y = header_y_start-20*mm

    if logo_image:
        try:
            logo_image.seek(0)
            img = Image.open(logo_image)

            target_width_mm = 40
            aspect_ratio = img.height / img.width
            target_height_mm = target_width_mm * aspect_ratio

            if target_height_mm > 25:
                target_height_mm = 25
                target_width_mm = target_height_mm / aspect_ratio

            logo_image.seek(0)
            c.drawImage(
                ImageReader(logo_image),
                logo_x,
                logo_y,
                width=target_width_mm*mm,
                height=target_height_mm*mm,
                preserveAspectRatio=True,
                mask='auto'
            )
        except Exception:
            c.setFillColor(colors.HexColor('#f0f0f0'))
            c.rect(logo_x, logo_y, 40*mm, 25*mm, fill=1, stroke=1)
            c.setFillColor(colors.black)
            c.setFont("Helvetica-Bold", 10)
            c.drawCentredString(logo_x+20*mm, logo_y+12.5*mm, "[LOGO]")
    else:
        c.setFillColor(colors.HexColor('#f0f0f0'))
        c.rect(logo_x, logo_y, 40*mm, 25*mm, fill=1, stroke=1)
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(logo_x+20*mm, logo_y+12.5*mm, "[LOGO]")

    # Client info - right side
    c.setFillColor(colors.black)
    x_client = 155*mm
    y_pos = header_y_start
    c.setFont("Helvetica-Bold", 8)
    c.drawString(x_client, y_pos, "CLIENT")
    y_pos -= 3.5*mm
    c.setFont("Helvetica", 7)
    c.drawString(x_client, y_pos, f"Nume: {remove_diacritics(safe_text(order.get('client_name','')))}")
    y_pos -= 3*mm
    c.drawString(x_client, y_pos, f"Tel: {safe_text(order.get('client_phone',''))}")

    # Title
    title_y = height-38*mm
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(105*mm, title_y, "DOVADA RIDICARE ECHIPAMENT DIN SERVICE")
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(colors.HexColor('#00aa00'))
    c.drawCentredString(105*mm, title_y-6*mm, f"Nr. Comanda: {safe_text(order.get('order_id',''))}")
    c.setFillColor(colors.black)

    # Three columns section
    y_start = height-50*mm
    col_width = 63*mm

    # LEFT COLUMN - Equipment details (MULTIPLE PRINTERS)
    x_left = 10*mm
    y_pos = y_start
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x_left, y_pos, "DETALII ECHIPAMENT:")
    y_pos -= 5*mm
    c.setFont("Helvetica", 8)

    printers = load_printers_from_order(order)
    if printers:
        for idx, p in enumerate(printers, start=1):
            brand = remove_diacritics(safe_text(p.get("brand", "")))
            model = remove_diacritics(safe_text(p.get("model", "")))
            serial = safe_text(p.get("serial", ""))

            line = f"{idx}. {brand} {model}"
            if serial:
                line += f" (SN: {serial})"

            c.drawString(x_left, y_pos, line)
            y_pos -= 4*mm
    else:
        printer_info = f"{remove_diacritics(safe_text(order.get('printer_brand','')))} {remove_diacritics(safe_text(order.get('printer_model','')))}"
        c.drawString(x_left, y_pos, f"Imprimanta: {printer_info}")
        y_pos -= 4*mm
        serial = safe_text(order.get('printer_serial',''))
        if serial:
            c.drawString(x_left, y_pos, f"Serie: {serial}")
            y_pos -= 4*mm

    c.drawString(x_left, y_pos, f"Data predarii: {safe_text(order.get('date_received',''))}")
    if order.get('date_picked_up'):
        y_pos -= 4*mm
        c.drawString(x_left, y_pos, f"Ridicare: {safe_text(order.get('date_picked_up',''))}")
    accessories = safe_text(order.get('accessories',''))
    if accessories and accessories.strip():
        y_pos -= 4*mm
        c.drawString(x_left, y_pos, f"Accesorii: {remove_diacritics(accessories)}")

    # MIDDLE COLUMN - Repairs
    x_middle = 73*mm
    y_pos = y_start
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x_middle, y_pos, "REPARATII EFECTUATE:")
    y_pos -= 3.5*mm
    c.setFont("Helvetica", 8)

    repair_text = remove_diacritics(safe_text(order.get('repair_details','N/A')))
    words = repair_text.split()
    line = ""
    line_count = 0
    max_lines = 5
    for word in words:
        test_line = line + word + " "
        if c.stringWidth(test_line, "Helvetica", 7) < (col_width-18*mm):
            line = test_line
        else:
            if line_count < max_lines:
                c.drawString(x_middle, y_pos, line.strip())
                y_pos -= 2.5*mm
                line_count += 1
                line = word + " "
            else:
                break
    if line and line_count < max_lines:
        c.drawString(x_middle, y_pos, line.strip())

    # RIGHT COLUMN - Parts used
    x_right = 136*mm
    y_pos = y_start
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x_right, y_pos, "PIESE UTILIZATE:")
    y_pos -= 3.5*mm
    c.setFont("Helvetica", 8)

    parts_text = remove_diacritics(safe_text(order.get('parts_used','N/A')))
    words = parts_text.split()
    line = ""
    line_count = 0
    max_lines = 5
    for word in words:
        test_line = line + word + " "
        if c.stringWidth(test_line, "Helvetica", 7) < (col_width-2*mm):
            line = test_line
        else:
            if line_count < max_lines:
                c.drawString(x_right, y_pos, line.strip())
                y_pos -= 2.5*mm
                line_count += 1
                line = word + " "
            else:
                break
    if line and line_count < max_lines:
        c.drawString(x_right, y_pos, line.strip())

    # Costs table
    y_cost = height-78*mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(10*mm, y_cost, "COSTURI:")
    y_cost -= 4*mm

    table_x = 10*mm
    table_width = 70*mm
    row_height = 5*mm

    # Table border
    c.rect(table_x, y_cost-(4*row_height), table_width, 4*row_height)

    # Header row
    c.setFillColor(colors.HexColor('#e0e0e0'))
    c.rect(table_x, y_cost-row_height, table_width, row_height, fill=1)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(table_x+2*mm, y_cost-row_height+1.5*mm, "Descriere")
    c.drawString(table_x+table_width-22*mm, y_cost-row_height+1.5*mm, "Suma (RON)")
    c.line(table_x, y_cost-row_height, table_x+table_width, y_cost-row_height)

    y_cost -= row_height

    # Labor row
    c.setFont("Helvetica", 8)
    c.drawString(table_x+2*mm, y_cost-row_height+1.5*mm, "Manopera")
    labor = safe_float(order.get('labor_cost',0))
    c.drawString(table_x+table_width-22*mm, y_cost-row_height+1.5*mm, f"{labor:.2f}")
    c.line(table_x, y_cost-row_height, table_x+table_width, y_cost-row_height)
    y_cost -= row_height

    # Parts row
    c.drawString(table_x+2*mm, y_cost-row_height+1.5*mm, "Piese")
    parts = safe_float(order.get('parts_cost',0))
    c.drawString(table_x+table_width-22*mm, y_cost-row_height+1.5*mm, f"{parts:.2f}")
    c.line(table_x, y_cost-row_height, table_x+table_width, y_cost-row_height)
    y_cost -= row_height

    # Total row
    c.setFillColor(colors.HexColor('#f0f0f0'))
    c.rect(table_x, y_cost-row_height, table_width, row_height, fill=1)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(table_x+2*mm, y_cost-row_height+1.5*mm, "TOTAL")
    total = safe_float(order.get('total_cost', labor+parts))
    c.drawString(table_x+table_width-22*mm, y_cost-row_height+1.5*mm, f"{total:.2f}")

    # Signature boxes
    sig_y = 22*mm
    sig_height = 18*mm

    c.rect(10*mm, sig_y, 85*mm, sig_height)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(12*mm, sig_y+sig_height-3*mm, "OPERATOR SERVICE")
    c.setFont("Helvetica", 7)
    c.drawString(12*mm, sig_y+2*mm, "Semnatura")

    c.rect(115*mm, sig_y, 85*mm, sig_height)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(117*mm, sig_y+sig_height-3*mm, "CLIENT")
    c.setFont("Helvetica", 7)
    c.drawString(117*mm, sig_y+sig_height-7*mm, "Am luat la cunostinta")
    c.drawString(117*mm, sig_y+2*mm, "Semnatura")

    # Footer
    c.setFont("Helvetica", 6)
    c.drawCentredString(105*mm, 3*mm, "Acest document constituie dovada ridicarii echipamentului din service.")
    c.setDash(3, 3)
    c.line(5*mm, 1*mm, 205*mm, 1*mm)

    c.save()
    buffer.seek(0)
    return buffer


# ============================================================================
# CRM CLASS - GOOGLE SHEETS BACKEND
# ============================================================================
class PrinterServiceCRM:
    def __init__(self, conn: GSheetsConnection):
        self.conn = conn
        self.worksheet = "Orders"
        self.next_order_id = 1
        self._init_sheet()

    def _read_df(self, raw: bool = True, ttl: int = 0) -> Optional[pd.DataFrame]:
        """Read Google Sheets into DataFrame safely."""
        try:
            df = self.conn.read(
                worksheet=self.worksheet,
                ttl=ttl
            )
            if df is None:
                return None
            if raw:
                return df
            return df.fillna("")
        except Exception as e:
            st.sidebar.error(f"❌ Error reading Google Sheets: {e}")
            return None

    def _write_df(self, df: pd.DataFrame, allow_empty: bool = False) -> bool:
        """Write entire DataFrame to Sheets. Prevents accidental data loss."""
        try:
            if df is None:
                st.sidebar.error("❌ Tried to write None DataFrame to Sheets.")
                return False
            if df.empty and not allow_empty:
                st.sidebar.error("⚠️ Refusing to write empty DataFrame to prevent data loss.")
                return False
            self.conn.update(worksheet=self.worksheet, data=df)
            st.sidebar.success("💾 Saved to Google Sheets!")
            return True
        except Exception as e:
            st.sidebar.error(f"❌ Error saving to Google Sheets: {e}")
            return False

    def _init_sheet(self):
        """Ensure headers exist and compute next_order_id with fill-the-gap logic."""
        df = self._read_df(raw=True, ttl=0)

        # CASE 1 — Sheet is missing or fully empty → create new sheet
        if df is None or df.empty:
            columns = [
                "order_id", "client_name", "client_phone", "client_email",
                "printer_brand", "printer_model", "printer_serial",
                "printers_json",
                "issue_description", "accessories", "notes",
                "date_received", "date_pickup_scheduled", "date_completed", "date_picked_up",
                "status", "technician", "repair_details", "parts_used",
                "labor_cost", "parts_cost", "total_cost",
            ]
            df = pd.DataFrame(columns=columns)
            self._write_df(df, allow_empty=False)
            self.next_order_id = 1
            return

        # CASE 2 — Sheet exists but order_id column is missing → recreate sheet header
        if "order_id" not in df.columns:
            columns = [
                "order_id", "client_name", "client_phone", "client_email",
                "printer_brand", "printer_model", "printer_serial",
                "printers_json",
                "issue_description", "accessories", "notes",
                "date_received", "date_pickup_scheduled", "date_completed", "date_picked_up",
                "status", "technician", "repair_details", "parts_used",
                "labor_cost", "parts_cost", "total_cost",
            ]
            new_df = pd.DataFrame(columns=columns)
            self._write_df(new_df, allow_empty=False)
            self.next_order_id = 1
            return

        # CASE 3 — Ensure printers_json exists
        if "printers_json" not in df.columns:
            df["printers_json"] = ""
            self._write_df(df, allow_empty=False)

        # CASE 4 — Determine next order ID with fill-the-gap logic
        existing = []
        for oid in df["order_id"]:
            try:
                if isinstance(oid, str) and oid.startswith("SRV-"):
                    num = int(oid.split("-")[1])
                    existing.append(num)
            except Exception:
                continue

        # CASE 4A — No existing IDs → start fresh
        if not existing:
            self.next_order_id = 1
            return

        existing_sorted = sorted(existing)

        # CASE 4B — Find the first missing ID
        missing = None
        for i in range(1, existing_sorted[-1] + 1):
            if i not in existing_sorted:
                missing = i
                break

        if missing:
            self.next_order_id = missing
        else:
            # No gaps → next is max + 1
            self.next_order_id = existing_sorted[-1] + 1

    def create_service_order(
        self,
        client_name,
        client_phone,
        client_email,
        printers_list,
        issue_description,
        accessories,
        notes,
        date_received,
        date_pickup
    ):
        order_id = f"SRV-{self.next_order_id:05d}"

        # First printer for legacy columns
        first_brand = ""
        first_model = ""
        first_serial = ""

        if printers_list:
            first_brand = safe_text(printers_list[0].get("brand", ""))
            first_model = safe_text(printers_list[0].get("model", ""))
            first_serial = safe_text(printers_list[0].get("serial", ""))

        printers_json = json.dumps(printers_list, ensure_ascii=False)

        def to_date_str(d):
            if isinstance(d, date):
                return d.strftime("%Y-%m-%d")
            if isinstance(d, str) and d.strip():
                return d
            return ""

        new_order = pd.DataFrame([{
            "order_id": order_id,
            "client_name": client_name,
            "client_phone": client_phone,
            "client_email": client_email,
            "printer_brand": first_brand,
            "printer_model": first_model,
            "printer_serial": first_serial,
            "printers_json": printers_json,
            "issue_description": issue_description,
            "accessories": accessories,
            "notes": notes,
            "date_received": to_date_str(date_received),
            "date_pickup_scheduled": to_date_str(date_pickup),
            "date_completed": "",
            "date_picked_up": "",
            "status": "Received",
            "technician": "",
            "repair_details": "",
            "parts_used": "",
            "labor_cost": 0.0,
            "parts_cost": 0.0,
            "total_cost": 0.0,
        }])

        df = self._read_df(raw=True, ttl=0)
        updated_df = pd.concat([df, new_order], ignore_index=True) if df is not None and not df.empty else new_order

        if self._write_df(updated_df):
            self.next_order_id += 1
            return order_id
        return None

    def list_orders_df(self) -> pd.DataFrame:
        df = self._read_df(raw=False, ttl=60)
        return df if df is not None else pd.DataFrame()

    def update_order(self, order_id: str, **kwargs) -> bool:
        """Update ONLY the matching row, write back entire DataFrame."""
        df = self._read_df(raw=True, ttl=0)
        if df is None or df.empty or "order_id" not in df.columns:
            st.sidebar.error("❌ Cannot update: no data found in Google Sheets.")
            return False

        mask = df["order_id"] == order_id
        if not mask.any():
            st.sidebar.error(f"❌ Order {order_id} not found in sheet.")
            return False

        for key, value in kwargs.items():
            if key in df.columns:
                df.loc[mask, key] = value

        if "labor_cost" in df.columns and "parts_cost" in df.columns:
            labor = pd.to_numeric(df.loc[mask, "labor_cost"], errors="coerce").fillna(0)
            parts = pd.to_numeric(df.loc[mask, "parts_cost"], errors="coerce").fillna(0)
            df.loc[mask, "total_cost"] = labor + parts

        return self._write_df(df)


# ============================================================================
# MAIN APP
# ============================================================================
def main():
    if not check_password():
        st.stop()

    st.title("🖨️ Printer Service CRM")
    st.markdown("### Professional Printer Service Management System")

    if "company_info" not in st.session_state:
        try:
            st.session_state["company_info"] = dict(st.secrets.get("company_info", {}))
        except Exception:
            st.session_state["company_info"] = {
                "company_name": "Company Name",
                "company_address": "Address",
                "cui": "CUI",
                "reg_com": "Reg.Com",
                "phone": "Phone",
                "email": "Email",
            }

    # Sidebar
    with st.sidebar:
        st.header("⚙️ Configuration")
        st.success(f"👤 {st.session_state.get('username', 'User')}")

        if st.button("🚪 Logout", key="logout_btn"):
            st.session_state["authenticated"] = False
            st.rerun()

        st.divider()

        with st.expander("🖼️ Company Logo", expanded=False):
            if st.session_state.get("logo_image"):
                st.image(st.session_state["logo_image"], width=150)
                st.success("✅ Logo loaded from repository")
            else:
                st.warning("⚠️ Logo not found")
                st.info("Add 'logo.png' to 'assets/' folder in your GitHub repo")

        with st.expander("🏢 Company Details", expanded=False):
            ci = st.session_state["company_info"]
            ci["company_name"] = st.text_input("Company Name", value=ci["company_name"], key="company_name_input")
            ci["company_address"] = st.text_input("Address", value=ci["company_address"], key="company_address_input")
            ci["cui"] = st.text_input("CUI", value=ci["cui"], key="company_cui_input")
            ci["reg_com"] = st.text_input("Reg.Com", value=ci["reg_com"], key="company_regcom_input")
            ci["phone"] = st.text_input("Phone", value=ci["phone"], key="company_phone_input")
            ci["email"] = st.text_input("Email", value=ci["email"], key="company_email_input")

        conn = get_sheets_connection()
        with st.expander("📊 Google Sheets", expanded=False):
            if conn:
                st.success("✅ Connected to Google Sheets!")
            else:
                st.error("❌ Not connected to Google Sheets")

    conn = get_sheets_connection()
    if not conn:
        st.error("Cannot connect to Google Sheets. Check secrets configuration.")
        st.stop()

    if "crm" not in st.session_state:
        st.session_state["crm"] = PrinterServiceCRM(conn)

    crm = st.session_state["crm"]
    df_all_orders = crm.list_orders_df()

    # Tab navigation
    tab_titles = ["📥 New Order", "📋 All Orders", "✏️ Update Order", "📊 Reports"]

    cols = st.columns(4)
    for idx, (col, title) in enumerate(zip(cols, tab_titles)):
        with col:
            if st.button(
                title,
                key=f"tab_btn_{idx}",
                use_container_width=True,
                type="primary" if st.session_state["active_tab"] == idx else "secondary",
            ):
                # memorează de pe ce tab vii
                st.session_state["last_tab"] = st.session_state["active_tab"]
                st.session_state["active_tab"] = idx
                st.rerun()

    st.divider()
    active_tab = st.session_state["active_tab"]

    # TAB 0: NEW ORDER
    if active_tab == 0:
        # dacă vii din alt tab, resetează starea de "ultimul order"
        if st.session_state.get("last_tab") != 0:
            st.session_state["last_created_order"] = None
            st.session_state["pdf_downloaded"] = False

        st.header("Create New Service Order")

        if not st.session_state["last_created_order"] or st.session_state["pdf_downloaded"]:
            # Ensure temp_printers exists
            if "temp_printers" not in st.session_state or not st.session_state["temp_printers"]:
                st.session_state["temp_printers"] = [{"brand": "", "model": "", "serial": ""}]

            with st.form(key="new_order_form", clear_on_submit=False):
                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("Client Information")
                    client_name = st.text_input("Name *", key="new_client_name")
                    client_phone = st.text_input("Phone *", key="new_client_phone")
                    client_email = st.text_input("Email", key="new_client_email")
                with col2:
                    st.subheader("Order Dates")
                    date_received = st.date_input("Date Received *", value=date.today(), key="new_date_received")
                    # dacă vrei, poți pune aici value=date.today() în loc de None
                    date_pickup = st.date_input("Scheduled Pickup (optional)", value=None, key="new_date_pickup")

                st.subheader("Printers in This Order")

                printers_list = st.session_state["temp_printers"]
                remove_flags = []

                # Draw each printer row
                for i, p in enumerate(printers_list):
                    st.markdown(f"**Printer #{i+1}**")
                    colA, colB, colC, colD = st.columns([1.2, 1.2, 1.2, 0.6])
                    with colA:
                        p["brand"] = st.text_input(f"Brand #{i+1} *", value=p["brand"], key=f"new_printer_brand_{i}")
                    with colB:
                        p["model"] = st.text_input(f"Model #{i+1} *", value=p["model"], key=f"new_printer_model_{i}")
                    with colC:
                        p["serial"] = st.text_input(f"Serial #{i+1}", value=p["serial"], key=f"new_printer_serial_{i}")
                    with colD:
                        remove_flags.append(
                            st.checkbox("Remove", key=f"new_printer_remove_{i}")
                        )

                issue_description = st.text_area("Issue Description *", height=100, key="new_issue_description")
                accessories = st.text_input("Accessories (cables, cartridges, etc.)", key="new_accessories")
                notes = st.text_area("Additional Notes", height=60, key="new_notes")

                col_btn1, col_btn2, col_btn3 = st.columns(3)
                with col_btn1:
                    remove_clicked = st.form_submit_button("🗑 Remove selected printers")
                with col_btn2:
                    add_clicked = st.form_submit_button("➕ Add another printer")
                with col_btn3:
                    submit = st.form_submit_button("🎫 Create Order", type="primary", use_container_width=True)

                if remove_clicked:
                    st.session_state["temp_printers"] = [
                        p for p, flag in zip(printers_list, remove_flags) if not flag
                    ]
                    if not st.session_state["temp_printers"]:
                        st.session_state["temp_printers"] = [{"brand": "", "model": "", "serial": ""}]
                    st.rerun()

                if add_clicked:
                    st.session_state["temp_printers"].append({"brand": "", "model": "", "serial": ""})
                    st.rerun()

                if submit:
                    # Clean printers list
                    printers_clean = []
                    for p in st.session_state["temp_printers"]:
                        brand = safe_text(p.get("brand", "")).strip()
                        model = safe_text(p.get("model", "")).strip()
                        serial = safe_text(p.get("serial", "")).strip()
                        if brand or model or serial:
                            printers_clean.append({
                                "brand": brand,
                                "model": model,
                                "serial": serial,
                            })

                    if not client_name or not client_phone or not issue_description:
                        st.error("❌ Please fill in all required fields (*) for client and issue.")
                    elif not printers_clean:
                        st.error("❌ Please add at least one printer (brand and model).")
                    else:
                        order_id = crm.create_service_order(
                            client_name, client_phone, client_email,
                            printers_clean,
                            issue_description, accessories, notes, date_received, date_pickup
                        )
                        if order_id:
                            st.session_state["last_created_order"] = order_id
                            st.session_state["pdf_downloaded"] = False
                            # Reset temp printers
                            st.session_state["temp_printers"] = [{"brand": "", "model": "", "serial": ""}]
                            st.success(f"✅ Order Created: **{order_id}**")
                            st.balloons()
                            st.rerun()

        if st.session_state["last_created_order"] and not st.session_state["pdf_downloaded"]:
            df_fresh = crm.list_orders_df()
            order_row = df_fresh[df_fresh["order_id"] == st.session_state["last_created_order"]]
            if not order_row.empty:
                order = order_row.iloc[0].to_dict()
                st.divider()
                st.success(f"✅ Order Created: **{order['order_id']}**")
                st.subheader("📄 Download Receipt")

                # Get logo from session state
                logo = st.session_state.get("logo_image", None)
                pdf_buffer = generate_initial_receipt_pdf(order, st.session_state["company_info"], logo)

                if st.download_button(
                    "📄 Download Initial Receipt",
                    pdf_buffer,
                    f"Initial_{order['order_id']}.pdf",
                    "application/pdf",
                    type="primary",
                    use_container_width=True,
                    key="dl_new_init",
                ):
                    st.session_state["last_created_order"] = None
                    st.session_state["pdf_downloaded"] = True
                    st.rerun()

    # TAB 1: ALL ORDERS
    elif active_tab == 1:
        st.header("All Service Orders")
        df = df_all_orders
        if not df.empty:
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("📊 Total Orders", len(df))
            col2.metric("📥 Received", len(df[df["status"] == "Received"]))
            col3.metric("✅ Ready", len(df[df["status"] == "Ready for Pickup"]))
            col4.metric("🎉 Completed", len(df[df["status"] == "Completed"]))

            st.markdown("**Click on a row to edit that order:**")

            event = st.dataframe(
                df[["order_id", "client_name", "printer_brand", "date_received", "status", "total_cost"]],
                use_container_width=True,
                selection_mode="single-row",
                on_select="rerun",
                key="orders_table"
            )

            if event and "selection" in event and event["selection"]["rows"]:
                selected_idx = event["selection"]["rows"][0]
                selected_order_id = df.iloc[selected_idx]["order_id"]

                st.session_state["selected_order_for_update"] = selected_order_id
                st.session_state["previous_selected_order"] = selected_order_id
                st.session_state["active_tab"] = 2
                st.rerun()

            csv = df.to_csv(index=False)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            st.download_button(
                "📥 Export to CSV",
                csv,
                f"orders_{ts}.csv",
                "text/csv",
                key="dl_csv",
                use_container_width=True,
            )
        else:
            st.info("📝 No orders yet. Create your first order in the 'New Order' tab!")

    # TAB 2: UPDATE ORDER
    elif active_tab == 2:
        st.header("Update Service Order")

        df = df_all_orders

        if not df.empty:
            available_orders = df["order_id"].tolist()

            default_idx = 0
            if st.session_state["selected_order_for_update"] in available_orders:
                default_idx = available_orders.index(st.session_state["selected_order_for_update"])

            def on_order_select():
                st.session_state["active_tab"] = 2

            selected_order_id = st.selectbox(
                "Select Order",
                available_orders,
                index=default_idx,
                key="update_order_select",
                label_visibility="collapsed",
                on_change=on_order_select
            )

            if selected_order_id:
                df_fresh = crm._read_df(raw=True, ttl=0)
                if df_fresh is None or df_fresh.empty:
                    st.error("❌ Error reading current data from Google Sheets.")
                else:
                    order_row = df_fresh[df_fresh["order_id"] == selected_order_id]

                    if order_row.empty:
                        st.error("❌ Order not found in current data.")
                    else:
                        order = order_row.iloc[0].to_dict()

                        # load printers for this order
                        printers_initial = load_printers_from_order(order)
                        state_key = f"upd_printers_{selected_order_id}"
                        if state_key not in st.session_state:
                            st.session_state[state_key] = printers_initial if printers_initial else [{"brand": "", "model": "", "serial": ""}]
                        current_printers = st.session_state[state_key]

                        col1, col2 = st.columns(2)
                        with col1:
                            st.write(f"**Client:** {safe_text(order.get('client_name'))}")
                            st.write(f"**Phone:** {safe_text(order.get('client_phone'))}")
                            st.write(f"**Printer (main):** {safe_text(order.get('printer_brand'))} {safe_text(order.get('printer_model'))}")
                            st.write(f"**Serial (main):** {safe_text(order.get('printer_serial'))}")
                        with col2:
                            st.write(f"**Received:** {safe_text(order.get('date_received'))}")
                            st.write(f"**Issue:** {safe_text(order.get('issue_description'))}")
                            st.write(f"**Accessories:** {safe_text(order.get('accessories'))}")

                        st.divider()

                        st.subheader("Printers in This Order")

                        remove_flags = []
                        for i, p in enumerate(current_printers):
                            st.markdown(f"**Printer #{i+1}**")
                            colA, colB, colC, colD = st.columns([1.2, 1.2, 1.2, 0.6])
                            with colA:
                                p["brand"] = st.text_input(f"Brand #{i+1}", value=p["brand"], key=f"upd_brand_{selected_order_id}_{i}")
                            with colB:
                                p["model"] = st.text_input(f"Model #{i+1}", value=p["model"], key=f"upd_model_{selected_order_id}_{i}")
                            with colC:
                                p["serial"] = st.text_input(f"Serial #{i+1}", value=p["serial"], key=f"upd_serial_{selected_order_id}_{i}")
                            with colD:
                                remove_flags.append(
                                    st.checkbox("Remove", key=f"upd_remove_printer_{selected_order_id}_{i}")
                                )

                        colp_r1, colp_r2 = st.columns(2)
                        with colp_r1:
                            if st.button("🗑 Remove selected", key=f"upd_remove_selected_{selected_order_id}"):
                                # 1) Ștergere locală
                                st.session_state[state_key] = [
                                    p for p, flag in zip(current_printers, remove_flags) if not flag
                                ]
                                if not st.session_state[state_key]:
                                    st.session_state[state_key] = [{"brand": "", "model": "", "serial": ""}]

                                # 2) Regenerăm JSON-ul pentru spreadsheet
                                printers_clean = []
                                for p in st.session_state[state_key]:
                                    brand = safe_text(p.get("brand", "")).strip()
                                    model = safe_text(p.get("model", "")).strip()
                                    serial = safe_text(p.get("serial", "")).strip()
                                    if brand or model or serial:
                                        printers_clean.append({
                                            "brand": brand,
                                            "model": model,
                                            "serial": serial,
                                        })

                                printers_json = json.dumps(printers_clean, ensure_ascii=False)

                                # 3) Actualizăm și câmpurile legacy
                                fb, fm, fs = "", "", ""
                                if printers_clean:
                                    fb, fm, fs = printers_clean[0]["brand"], printers_clean[0]["model"], printers_clean[0]["serial"]

                                # 4) Scriem în spreadsheet imediat
                                crm.update_order(
                                    selected_order_id,
                                    printers_json=printers_json,
                                    printer_brand=fb,
                                    printer_model=fm,
                                    printer_serial=fs
                                )

                                # 5) Reafișăm pagina
                                st.success("🗑 Imprimantele selectate au fost șterse!")
                                st.rerun()

                        with colp_r2:
                            if st.button("➕ Add printer", key=f"upd_add_printer_btn_{selected_order_id}"):
                                printers_list = st.session_state.get(state_key, [])
                                printers_list.append({"brand": "", "model": "", "serial": ""})
                                st.session_state[state_key] = printers_list
                                st.rerun()

                        st.divider()

                        status_options = ["Received", "In Progress", "Ready for Pickup", "Completed"]
                        current_status = safe_text(order.get("status")) or "Received"
                        if current_status not in status_options:
                            current_status = "Received"
                        status_index = status_options.index(current_status)

                        new_status = st.selectbox(
                            "Status",
                            status_options,
                            index=status_index,
                            key=f"update_status_{selected_order_id}",
                        )

                        if new_status == "Completed":
                            actual_pickup_date = st.date_input(
                                "Actual Pickup Date",
                                value=date.today(),
                                key=f"update_pickup_date_{selected_order_id}",
                            )
                        else:
                            actual_pickup_date = None

                        st.subheader("Repair details")

                        repair_details = st.text_area(
                            "Repairs performed",
                            value=safe_text(order.get("repair_details")),
                            height=100,
                            key=f"update_repair_details_{selected_order_id}",
                        )

                        parts_used = st.text_input(
                            "Parts used",
                            value=safe_text(order.get("parts_used")),
                            key=f"update_parts_used_{selected_order_id}",
                        )

                        technician = st.text_input(
                            "Technician",
                            value=safe_text(order.get("technician")),
                            key=f"update_technician_{selected_order_id}",
                        )

                        colc1, colc2, colc3 = st.columns(3)
                        labor_cost = colc1.number_input(
                            "Labor cost (RON)",
                            value=safe_float(order.get("labor_cost")),
                            min_value=0.0,
                            step=10.0,
                            key=f"update_labor_cost_{selected_order_id}",
                        )
                        parts_cost = colc2.number_input(
                            "Parts cost (RON)",
                            value=safe_float(order.get("parts_cost")),
                            min_value=0.0,
                            step=10.0,
                            key=f"update_parts_cost_{selected_order_id}",
                        )
                        colc3.metric("💰 Total", f"{labor_cost + parts_cost:.2f} RON")

                        if st.button("💾 Update Order", type="primary", key=f"update_order_btn_{selected_order_id}"):
                            # Clean printers list
                            printers_clean = []
                            for p in st.session_state[state_key]:
                                brand = safe_text(p.get("brand", "")).strip()
                                model = safe_text(p.get("model", "")).strip()
                                serial = safe_text(p.get("serial", "")).strip()
                                if brand or model or serial:
                                    printers_clean.append({
                                        "brand": brand,
                                        "model": model,
                                        "serial": serial,
                                    })

                            printers_json = json.dumps(printers_clean, ensure_ascii=False)

                            first_brand = ""
                            first_model = ""
                            first_serial = ""
                            if printers_clean:
                                first_brand = printers_clean[0]["brand"]
                                first_model = printers_clean[0]["model"]
                                first_serial = printers_clean[0]["serial"]

                            updates = {
                                "status": new_status,
                                "repair_details": repair_details,
                                "parts_used": parts_used,
                                "technician": technician,
                                "labor_cost": labor_cost,
                                "parts_cost": parts_cost,
                                "printers_json": printers_json,
                                "printer_brand": first_brand,
                                "printer_model": first_model,
                                "printer_serial": first_serial,
                            }

                            if new_status == "Ready for Pickup" and not order.get("date_completed"):
                                updates["date_completed"] = datetime.now().strftime("%Y-%m-%d")
                            if new_status == "Completed":
                                updates["date_picked_up"] = (
                                    actual_pickup_date.strftime("%Y-%m-%d")
                                    if actual_pickup_date
                                    else datetime.now().strftime("%Y-%m-%d")
                                )

                            if crm.update_order(selected_order_id, **updates):
                                st.success("✅ Order updated successfully!")
                                st.rerun()

                        st.divider()
                        st.subheader("📄 Download Receipts")

                        # Re-citim comanda proaspăt din sheet pentru PDF-uri actualizate
                        df_latest = crm._read_df(raw=True, ttl=0)
                        if df_latest is not None and not df_latest.empty:
                            mask = df_latest["order_id"] == selected_order_id
                            if mask.any():
                                order_latest = df_latest[mask].iloc[0].to_dict()
                            else:
                                order_latest = order  # fallback la varianta veche deja încărcată
                        else:
                            order_latest = order

                        logo = st.session_state.get("logo_image", None)

                        colp1, colp2 = st.columns(2)
                        with colp1:
                            st.markdown("**Initial Receipt**")
                            pdf_init = generate_initial_receipt_pdf(order_latest, st.session_state["company_info"], logo)
                            st.download_button(
                                "📄 Download Initial",
                                pdf_init,
                                f"Initial_{order_latest['order_id']}.pdf",
                                "application/pdf",
                                use_container_width=True,
                                key=f"dl_upd_init_{order_latest['order_id']}",
                            )
                        with colp2:
                            st.markdown("**Completion Receipt**")
                            pdf_comp = generate_completion_receipt_pdf(order_latest, st.session_state["company_info"], logo)
                            st.download_button(
                                "📄 Download Completion",
                                pdf_comp,
                                f"Completion_{order_latest['order_id']}.pdf",
                                "application/pdf",
                                use_container_width=True,
                                key=f"dl_upd_comp_{order_latest['order_id']}",
                            )
        else:
            st.info("📝 No orders yet.")

    # TAB 3: REPORTS
    elif active_tab == 3:
        st.header("Reports & Analytics")
        df = df_all_orders
        if not df.empty:
            col1, col2, col3 = st.columns(3)
            col1.metric("💰 Total Revenue", f"{df['total_cost'].sum():.2f} RON")
            avg_cost = df[df["total_cost"] > 0]["total_cost"].mean() if len(df[df["total_cost"] > 0]) > 0 else 0
            col2.metric("📊 Average Cost", f"{avg_cost:.2f} RON")
            col3.metric("👥 Unique Clients", df["client_name"].nunique())

            st.divider()
            st.subheader("Orders by Status")
            st.bar_chart(df["status"].value_counts())
        else:
            st.info("📝 No data yet.")


if __name__ == "__main__":
    main()
