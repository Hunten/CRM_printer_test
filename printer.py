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

# For new-order temporary printers - MODIFICAT: ADAUGAT 'warranty'
if "temp_printers" not in st.session_state:
    st.session_state["temp_printers"] = [{"brand": "", "model": "", "serial": "", "warranty": False}]


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

# MODIFICAT: Adaugat 'warranty' in structura returnata
def load_printers_from_order(order: dict):
    """
    Returnează o listă de imprimante din order:
    - încearcă printers_json
    - dacă e gol, folosește printer_brand/model/serial legacy
    - ADAUGA 'warranty' (default False)
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
                "serial": serial,
                "warranty": False # Default pentru legacy
            }]
    
    # asigura structura (inclusiv noul camp warranty)
    cleaned = []
    for p in printers:
        cleaned.append({
            "brand": safe_text(p.get("brand", "")),
            "model": safe_text(p.get("model", "")),
            "serial": safe_text(p.get("serial", "")),
            "warranty": bool(p.get("warranty", False)), # se asigura ca e boolean
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
        st.sidebar.error(f"Google Sheets connection failed: {e}")
        return None

# MODIFICAT: Afisare 'Sub Garantie'/'Fara Garantie' pe bonul de primire
def generate_initial_receipt_pdf(order, company_info, logo_image=None):
    """Generate A4 PDF with TWO identical A5 receipts (top + bottom)."""
    buffer = io.BytesIO()

    width = 210 * mm         # A4 width
    a5_height = 148.5 * mm   # A5 height
    total_height = 2 * a5_height

    c = canvas.Canvas(buffer, pagesize=(width, total_height))

    def draw_half(offset_y: float):
        """
        Deseneaza un bon A5 complet, pornind de la offset_y (bottom-ul
        acestei jumatati). Layout-ul este identic cu cel vechi A5.
        """
        # Topul acestei jumatati A5
        top = offset_y + a5_height

        # Logo + date firma
        header_y_start = top - 10 * mm
        x_business = 10 * mm
        y_pos = header_y_start

        # Company info - left side
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x_business, y_pos, remove_diacritics(company_info.get('company_name', '')))
        y_pos -= 3.5 * mm
        c.setFont("Helvetica", 7)
        c.drawString(x_business, y_pos, remove_diacritics(company_info.get('company_address', '')))
        y_pos -= 3 * mm
        c.drawString(x_business, y_pos, f"CUI: {company_info.get('cui', '')}")
        y_pos -= 3 * mm
        c.drawString(x_business, y_pos, f"Reg.Com: {company_info.get('reg_com', '')}")
        y_pos -= 3 * mm
        c.drawString(x_business, y_pos, f"Tel: {company_info.get('phone', '')}")
        y_pos -= 3 * mm
        c.drawString(x_business, y_pos, f"Email: {company_info.get('email', '')}")

        # Logo middle
        logo_x = 85 * mm
        logo_y = header_y_start - 20 * mm

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
                    width=target_width_mm * mm,
                    height=target_height_mm * mm,
                    preserveAspectRatio=True,
                    mask='auto'
                )
            except Exception:
                c.setFillColor(colors.HexColor('#f0f0f0'))
                c.rect(logo_x, logo_y, 40 * mm, 25 * mm, fill=1, stroke=1)
                c.setFillColor(colors.black)
                c.setFont("Helvetica-Bold", 10)
                c.drawCentredString(logo_x + 20 * mm, logo_y + 12.5 * mm, "[LOGO]")
        else:
            c.setFillColor(colors.HexColor('#f0f0f0'))
            c.rect(logo_x, logo_y, 40 * mm, 25 * mm, fill=1, stroke=1)
            c.setFillColor(colors.black)
            c.setFont("Helvetica-Bold", 10)
            c.drawCentredString(logo_x + 20 * mm, logo_y + 12.5 * mm, "[LOGO]")

        # Client info - right side
        c.setFillColor(colors.black)
        x_client = 155 * mm
        y_pos = header_y_start
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x_client, y_pos, "CLIENT")
        y_pos -= 3.5 * mm
        c.setFont("Helvetica", 7)
        c.drawString(x_client, y_pos, f"Nume: {remove_diacritics(safe_text(order.get('client_name', '')))}")
        y_pos -= 3 * mm
        c.drawString(x_client, y_pos, f"Tel: {safe_text(order.get('client_phone', ''))}")

        # Title
        title_y = top - 38 * mm
        c.setFont("Helvetica-Bold", 12)
        c.drawCentredString(105 * mm, title_y, "DOVADA PREDARE ECHIPAMENT IN SERVICE")
        c.setFont("Helvetica-Bold", 10)
        c.setFillColor(colors.HexColor('#E5283A'))
        c.drawCentredString(105 * mm, title_y - 6 * mm, f"Nr. Comanda: {safe_text(order.get('order_id', ''))}")
        c.setFillColor(colors.black)

        # Equipment details (MULTIPLE PRINTERS)
        y_pos = top - 50 * mm
        c.setFont("Helvetica-Bold", 9)
        c.drawString(10 * mm, y_pos, "DETALII ECHIPAMENT:")
        y_pos -= 5 * mm
        c.setFont("Helvetica", 8)

        printers = load_printers_from_order(order)

        if printers:
            for idx, p in enumerate(printers, start=1):
                brand = remove_diacritics(safe_text(p.get("brand", "")))
                model = remove_diacritics(safe_text(p.get("model", "")))
                serial = safe_text(p.get("serial", ""))
                # NOU: Garanție
                warranty = p.get("warranty", False)

                line = f"{idx}. {brand} {model}"
                if serial:
                    line += f" (SN: {serial})"
                # NOU: Adaugă detalii Garanție pe bon
                if warranty:
                    line += " [Sub Garantie]"
                else:
                    line += " [Fara Garantie]"


                c.drawString(10 * mm, y_pos, line)
                y_pos -= 4 * mm
        else:
            # fallback daca totusi nu exista nicio imprimanta
            printer_info = f"{remove_diacritics(safe_text(order.get('printer_brand', '')))} {remove_diacritics(safe_text(order.get('printer_model', '')))}"
            c.drawString(10 * mm, y_pos, f"Imprimanta: {printer_info}")
            y_pos -= 4 * mm
            serial = safe_text(order.get('printer_serial', ''))
            if serial:
                c.drawString(10 * mm, y_pos, f"Serie: {serial}")
                y_pos -= 4 * mm

        # Data si accesorii - la nivel de comanda
        c.drawString(10 * mm, y_pos, f"Data predarii: {safe_text(order.get('date_received', ''))}")
        y_pos -= 4 * mm

        accessories = safe_text(order.get('accessories', ''))
        if accessories and accessories.strip():
            c.drawString(10 * mm, y_pos, f"Accesorii: {remove_diacritics(accessories)}")
            y_pos -= 4 * mm

        # Issue description
        y_pos -= 2 * mm
        c.setFont("Helvetica-Bold", 9)
        c.drawString(10 * mm, y_pos, "PROBLEMA RAPORTATA:")
        y_pos -= 4 * mm
        c.setFont("Helvetica", 8)

        issue_text = remove_diacritics(safe_text(order.get('issue_description', '')))
        text_object = c.beginText(10 * mm, y_pos)
        text_object.setFont("Helvetica", 8)
        words = issue_text.split()
        line = ""
        for word in words:
            test_line = line + word + " "
            if c.stringWidth(test_line, "Helvetica", 8) < 190 * mm:
                line = test_line
            else:
                text_object.textLine(line)
                line = word + " "
        if line:
            text_object.textLine(line)
        c.drawText(text_object)

        # Signature boxes
        sig_y = offset_y + 22 * mm
        sig_height = 18 * mm

        c.rect(10 * mm, sig_y, 85 * mm, sig_height)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(12 * mm, sig_y + sig_height - 3 * mm, "OPERATOR SERVICE")
        c.setFont("Helvetica", 7)
        c.drawString(12 * mm, sig_y + 2 * mm, "Semnatura")

        c.rect(115 * mm, sig_y, 85 * mm, sig_height)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(117 * mm, sig_y + sig_height - 3 * mm, "CLIENT")
        c.setFont("Helvetica", 7)
        c.drawString(117 * mm, sig_y + sig_height - 7 * mm, "Am luat la cunostinta")
        c.drawString(117 * mm, sig_y + 2 * mm, "Semnatura")

        # more info (footer text for aceasta jumatate A5)
        c.setFont("Helvetica-Bold", 7)
        c.drawCentredString(105 * mm, offset_y + 18 * mm,
                             "Avand in vedere ca dispozitivele din prezenta fisa nu au putut fi testate in momentul preluarii lor, acestea sunt considerate ca fiind nefunctionale.")
        c.setFont("Helvetica", 7)
        c.drawCentredString(105 * mm, offset_y + 15 * mm,
                             "Aveti obligatia ca, la finalizarea reparatiei echipamentului aflat in service, sa va prezentati in termen de 30 de zile de la data anuntarii de catre")
        c.setFont("Helvetica", 7)
        c.drawCentredString(105 * mm, offset_y + 12 * mm,
                             "reprezentantul SC PRINTHEAD COMPLETE SOLUTIONS SRL pentru a ridica echipamentul.In cazul neridicarii echipamentului")
        c.setFont("Helvetica", 7)
        c.drawCentredString(105 * mm, offset_y + 9 * mm,
                             "in intervalul specificat mai sus, ne rezervam dreptul de valorificare a acestuia")

        # Footer
        c.setFont("Helvetica", 6)
        c.drawCentredString(105 * mm, offset_y + 3 * mm,
                             "Acest document constituie dovada predarii echipamentului in service.")
        c.setDash(3, 3)
        c.line(5 * mm, offset_y + 1 * mm, 205 * mm, offset_y + 1 * mm)
        c.setDash()

    # Desenam doua jumatati A5 pe aceeasi pagina A4
    draw_half(0)         # jumatatea de jos
    draw_half(a5_height) # jumatatea de sus

    c.save()
    buffer.seek(0)
    return buffer




def generate_completion_receipt_pdf(order, company_info, logo_image=None):
    """Generate A4 PDF with TWO identical A5 completion receipts (top + bottom)."""
    buffer = io.BytesIO()

    width = 210 * mm         # A4 width
    a5_height = 148.5 * mm   # A5 height
    total_height = 2 * a5_height

    c = canvas.Canvas(buffer, pagesize=(width, total_height))
    SHIFT_BOXES = -15 * mm
    

    def draw_half(offset_y: float):
        """
        Deseneaza un bon de ridicare A5 complet, pornind de la offset_y.
        Layout-ul ramane identic cu cel vechi.
        """
        top = offset_y + a5_height

        header_y_start = top - 10 * mm
        x_business = 10 * mm
        y_pos = header_y_start

        # Company info - left side
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x_business, y_pos, remove_diacritics(company_info.get('company_name', '')))
        y_pos -= 3.5 * mm
        c.setFont("Helvetica", 7)
        c.drawString(x_business, y_pos, remove_diacritics(company_info.get('company_address', '')))
        y_pos -= 3 * mm
        c.drawString(x_business, y_pos, f"CUI: {company_info.get('cui', '')}")
        y_pos -= 3 * mm
        c.drawString(x_business, y_pos, f"Reg.Com: {company_info.get('reg_com', '')}")
        y_pos -= 3 * mm
        c.drawString(x_business, y_pos, f"Tel: {company_info.get('phone', '')}")
        y_pos -= 3 * mm
        c.drawString(x_business, y_pos, f"Email: {company_info.get('email', '')}")

        # Logo middle
        logo_x = 85 * mm
        logo_y = header_y_start - 20 * mm

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
                    width=target_width_mm * mm,
                    height=target_height_mm * mm,
                    preserveAspectRatio=True,
                    mask='auto'
                )
            except Exception:
                c.setFillColor(colors.HexColor('#f0f0f0'))
                c.rect(logo_x, logo_y, 40 * mm, 25 * mm, fill=1, stroke=1)
                c.setFillColor(colors.black)
                c.setFont("Helvetica-Bold", 10)
                c.drawCentredString(logo_x + 20 * mm, logo_y + 12.5 * mm, "[LOGO]")
        else:
            c.setFillColor(colors.HexColor('#f0f0f0'))
            c.rect(logo_x, logo_y, 40 * mm, 25 * mm, fill=1, stroke=1)
            c.setFillColor(colors.black)
            c.setFont("Helvetica-Bold", 10)
            c.drawCentredString(logo_x + 20 * mm, logo_y + 12.5 * mm, "[LOGO]")

        # Client info - right side
        c.setFillColor(colors.black)
        x_client = 155 * mm
        y_pos = header_y_start
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x_client, y_pos, "CLIENT")
        y_pos -= 3.5 * mm
        c.setFont("Helvetica", 7)
        c.drawString(x_client, y_pos, f"Nume: {remove_diacritics(safe_text(order.get('client_name', '')))}")
        y_pos -= 3 * mm
        c.drawString(x_client, y_pos, f"Tel: {safe_text(order.get('client_phone', ''))}")

        # Title
        title_y = top - 38 * mm
        c.setFont("Helvetica-Bold", 12)
        c.drawCentredString(105 * mm, title_y, "DOVADA RIDICARE ECHIPAMENT DIN SERVICE")
        c.setFont("Helvetica-Bold", 10)
        c.setFillColor(colors.HexColor('#00aa00'))
        c.drawCentredString(105 * mm, title_y - 6 * mm, f"Nr. Comanda: {safe_text(order.get('order_id', ''))}")
        c.setFillColor(colors.black)

        # Three columns section
        y_start = top - 50 * mm
        col_width = 63 * mm

        # LEFT COLUMN - Equipment details (MULTIPLE PRINTERS)
        x_left = 10 * mm
        y_pos = y_start
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x_left, y_pos, "DETALII ECHIPAMENT:")
        y_pos -= 5 * mm
        c.setFont("Helvetica", 8)

        printers = load_printers_from_order(order)
        if printers:
            for idx, p in enumerate(printers, start=1):
                brand = remove_diacritics(safe_text(p.get("brand", "")))
                model = remove_diacritics(safe_text(p.get("model", "")))
                serial = safe_text(p.get("serial", ""))
                
                # NOU: Garanție pe bonul de ridicare
                warranty = p.get("warranty", False)

                line = f"{idx}. {brand} {model}"
                if serial:
                    line += f" (SN: {serial})"
                
                # NOU: Adaugă detalii Garanție
                if warranty:
                    line += " [Sub Garantie]"
                else:
                    line += " [Fara Garantie]"


                c.drawString(x_left, y_pos, line)
                y_pos -= 4 * mm
        else:
            printer_info = f"{remove_diacritics(safe_text(order.get('printer_brand', '')))} {remove_diacritics(safe_text(order.get('printer_model', '')))}"
            c.drawString(x_left, y_pos, f"Imprimanta: {printer_info}")
            y_pos -= 4 * mm
            serial = safe_text(order.get('printer_serial', ''))
            if serial:
                c.drawString(x_left, y_pos, f"Serie: {serial}")
                y_pos -= 4 * mm

        c.drawString(x_left, y_pos, f"Data predarii: {safe_text(order.get('date_received', ''))}")
        if order.get('date_picked_up'):
            y_pos -= 4 * mm
            c.drawString(x_left, y_pos, f"Ridicare: {safe_text(order.get('date_picked_up', ''))}")
        accessories = safe_text(order.get('accessories', ''))
        if accessories and accessories.strip():
            y_pos -= 4 * mm
            c.drawString(x_left, y_pos, f"Accesorii: {remove_diacritics(accessories)}")

        # MIDDLE COLUMN - Repairs
        x_middle = 73 * mm
        y_pos = y_start
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x_middle, y_pos, "REPARATII EFECTUATE:")
        y_pos -= 3.5 * mm
        c.setFont("Helvetica", 8)

        repair_text = remove_diacritics(safe_text(order.get('repair_details', 'N/A')))
        words = repair_text.split()
        line = ""
        line_count = 0
        max_lines = 5
        for word in words:
            test_line = line + word + " "
            if c.stringWidth(test_line, "Helvetica", 7) < (col_width - 18 * mm):
                line = test_line
            else:
                if line_count < max_lines:
                    c.drawString(x_middle, y_pos, line.strip())
                    y_pos -= 2.5 * mm
                    line_count += 1
                    line = word + " "
                else:
                    break
        if line and line_count < max_lines:
            c.drawString(x_middle, y_pos, line.strip())

        # RIGHT COLUMN - Parts used
        x_right = 136 * mm
        y_pos = y_start
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x_right, y_pos, "PIESE UTILIZATE:")
        y_pos -= 3.5 * mm
        c.setFont("Helvetica", 8)

        parts_text = remove_diacritics(safe_text(order.get('parts_used', 'N/A')))
        words = parts_text.split()
        line = ""
        line_count = 0
        max_lines = 5
        for word in words:
            test_line = line + word + " "
            if c.stringWidth(test_line, "Helvetica", 7) < (col_width - 2 * mm):
                line = test_line
            else:
                if line_count < max_lines:
                    c.drawString(x_right, y_pos, line.strip())
                    y_pos -= 2.5 * mm
                    line_count += 1
                    line = word + " "
                else:
                    break
        if line and line_count < max_lines:
            c.drawString(x_right, y_pos, line.strip())

        # ------------------------------
        # COST TABLE (shifted down 15mm)
        # ------------------------------
        y_cost = top - 78 * mm + SHIFT_BOXES
        c.setFont("Helvetica-Bold", 9)
        c.drawString(10 * mm, y_cost, "COSTURI:")
        y_cost -= 4 * mm

        table_x = 10 * mm
        table_width = 70 * mm
        row_height = 5 * mm

        c.rect(table_x, y_cost - (4 * row_height), table_width, 4 * row_height)

        c.setFillColor(colors.HexColor('#e0e0e0'))
        c.rect(table_x, y_cost - row_height, table_width, row_height, fill=1)
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(table_x + 2 * mm, y_cost - row_height + 1.5 * mm, "Descriere")
        c.drawString(table_x + table_width - 22 * mm, y_cost - row_height + 1.5 * mm, "Suma (RON)")
        c.line(table_x, y_cost - row_height, table_x + table_width, y_cost - row_height)

        y_cost -= row_height

        c.setFont("Helvetica", 8)
        c.drawString(table_x + 2 * mm, y_cost - row_height + 1.5 * mm, "Manopera")
        labor = safe_float(order.get('labor_cost', 0))
        c.drawString(table_x + table_width - 22 * mm, y_cost - row_height + 1.5 * mm, f"{labor:.2f}")
        c.line(table_x, y_cost - row_height, table_x + table_width, y_cost - row_height)
        y_cost -= row_height

        c.drawString(table_x + 2 * mm, y_cost - row_height + 1.5 * mm, "Piese")
        parts = safe_float(order.get('parts_cost', 0))
        c.drawString(table_x + table_width - 22 * mm, y_cost - row_height + 1.5 * mm, f"{parts:.2f}")
        c.line(table_x, y_cost - row_height, table_x + table_width, y_cost - row_height)
        y_cost -= row_height

        c.setFillColor(colors.HexColor('#f0f0f0'))
        c.rect(table_x, y_cost - row_height, table_width, row_height, fill=1)
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(table_x + 2 * mm, y_cost - row_height + 1.5 * mm, "TOTAL")
        total = safe_float(order.get('total_cost', labor + parts))
        c.drawString(table_x + table_width - 22 * mm, y_cost - row_height + 1.5 * mm, f"{total:.2f}")

        # ------------------------------
        # SIGNATURE BOXES (shifted down)
        # ------------------------------
        sig_y = offset_y + 22 * mm + SHIFT_BOXES
        sig_height = 18 * mm

        c.rect(10 * mm, sig_y, 85 * mm, sig_height)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(12 * mm, sig_y + sig_height - 3 * mm, "OPERATOR SERVICE")
        c.setFont("Helvetica", 7)
        c.drawString(12 * mm, sig_y + 2 * mm, "Semnatura")

        c.rect(115 * mm, sig_y, 85 * mm, sig_height)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(117 * mm, sig_y + sig_height - 3 * mm, "CLIENT")
        c.setFont("Helvetica", 7)
        c.drawString(117 * mm, sig_y + sig_height - 7 * mm, "Am luat la cunostinta")
        c.drawString(117 * mm, sig_y + 2 * mm, "Semnatura")

        # footer unchanged
        c.setFont("Helvetica", 6)
        c.drawCentredString(105 * mm, offset_y + 3 * mm,
                             "Acest document constituie dovada ridicarii echipamentului din service.")
        c.setDash(3, 3)
        c.line(5 * mm, offset_y + 1 * mm, 205 * mm, offset_y + 1 * mm)
        c.setDash()

    draw_half(0)
    draw_half(a5_height)

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

    @st.cache_data(ttl=0) # Cache to avoid reading on every interaction
    def get_all_orders(_self) -> Optional[pd.DataFrame]:
        """Read all orders from Google Sheets."""
        return _self._read_df(raw=False, ttl=0)

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
            
            # Reset index needed for writing
            df = df.reset_index(drop=True)
            self.conn.update(worksheet=self.worksheet, data=df)
            
            # Clear cache for instant refresh
            self.get_all_orders.clear() 
            st.sidebar.success("💾 Saved to Google Sheets!")
            return True
        except Exception as e:
            st.sidebar.error(f"❌ Error saving to Google Sheets: {e}")
            return False

    def _init_sheet(self):
        """Ensure headers exist and compute next_order_id with fill-the-gap logic."""
        df = self._read_df(raw=True, ttl=0)

        # Definirea coloanelor standard (inclusiv noul 'printers_json')
        STANDARD_COLUMNS = [
            "order_id", "client_name", "client_phone", "client_email",
            "printer_brand", "printer_model", "printer_serial",
            "printers_json", # Colana pentru JSON cu multiple imprimante (inclusiv warranty)
            "issue_description", "accessories", "notes",
            "date_received", "date_pickup_scheduled", "date_completed", "date_picked_up",
            "status", "technician", "repair_details", "parts_used",
            "labor_cost", "parts_cost", "total_cost",
        ]


        # CASE 1 — Sheet is missing or fully empty → create new sheet
        if df is None or df.empty or not any(col in df.columns for col in STANDARD_COLUMNS):
            df = pd.DataFrame(columns=STANDARD_COLUMNS)
            self._write_df(df, allow_empty=True) # Allow writing empty DF here
            self.next_order_id = 1
            return

        # CASE 2 — Ensure all standard columns exist (backward compatibility)
        should_rewrite = False
        for col in STANDARD_COLUMNS:
            if col not in df.columns:
                df[col] = ""
                should_rewrite = True

        if should_rewrite:
            df = df[STANDARD_COLUMNS] # Reorder and select only standard columns
            self._write_df(df, allow_empty=False)

        # CASE 3 — Determine next order ID with fill-the-gap logic
        existing = []
        for oid in df["order_id"]:
            try:
                if isinstance(oid, str) and oid.startswith("SRV-"):
                    num = int(oid.split("-")[1])
                    existing.append(num)
            except Exception:
                continue

        # CASE 3A — No existing IDs → start fresh
        if not existing:
            self.next_order_id = 1
            return

        existing_sorted = sorted(existing)

        # CASE 3B — Find the first missing ID
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

    # MODIFICAT: ELIMINAT ARGUMENTUL has_warranty
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

        # MODIFICAT: ELIMINAT CÂMPUL "has_warranty" din DataFrame
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

        df = self.get_all_orders()
        if df is None:
            df = new_order
        else:
            df = pd.concat([df, new_order], ignore_index=True)

        if self._write_df(df, allow_empty=False):
            # Recompute next ID after successful save
            self._init_sheet()
            return order_id
        return None

    def update_service_order(self, order_id, updates: dict):
        df = self.get_all_orders()
        if df is None or df.empty:
            return False

        idx_to_update = df[df['order_id'] == order_id].index

        if idx_to_update.empty:
            return False

        # Apply updates to the specific row
        for key, value in updates.items():
            if key in df.columns:
                df.loc[idx_to_update, key] = value

        return self._write_df(df, allow_empty=False)


# ============================================================================
# STREAMLIT APP LAYOUT
# ============================================================================

def main():
    conn = get_sheets_connection()
    if conn is None:
        st.stop()

    if not check_password():
        st.stop()
    
    # Load CRM instance
    crm = PrinterServiceCRM(conn)
    df_all_orders = crm.get_all_orders()
    if df_all_orders is None:
        st.error("Cannot load order data.")
        df_all_orders = pd.DataFrame()
        # st.stop() # Uncomment to stop the app if data is crucial


    # --- Sidebar and Global Elements ---
    logo = st.session_state["logo_image"]
    
    col_logo, col_title = st.columns([1, 4])
    with col_logo:
        if logo:
            st.image(logo, use_column_width="always")
    with col_title:
        st.title("PRINTHEAD Service CRM")

    # Company Info (Hardcoded for PDF generation)
    if "company_info" not in st.session_state:
        st.session_state["company_info"] = {
            "company_name": "SC PRINTHEAD COMPLETE SOLUTIONS SRL",
            "company_address": "Str. Exemplelor nr. 1, Cluj-Napoca, Romania",
            "cui": "RO12345678",
            "reg_com": "J12/123/2020",
            "phone": "07xx xxx xxx",
            "email": "contact@printhead.ro",
        }

    st.sidebar.markdown(f"**Logged in as:** `{st.session_state['username']}`")
    st.sidebar.markdown(f"**Next Order ID:** `SRV-{crm.next_order_id:05d}`")
    st.sidebar.caption("Data is loaded from Google Sheets.")

    tab_names = ["➕ New Service Order", "🔎 View/Search", "⚙️ Update/Complete Order", "📊 Reports"]
    
    # Manages tab switching via session state
    active_tab = st.session_state["active_tab"]
    
    tabs = st.tabs(tab_names)

    # --- TAB 0: NEW ORDER ---
    with tabs[0]:
        st.session_state["active_tab"] = 0
        st.header(tab_names[0])
        st.subheader(f"Order ID: **SRV-{crm.next_order_id:05d}**")

        # Start of Form
        with st.form("new_order_form", clear_on_submit=True):
            st.markdown("### 🧑 Client Details")
            col1, col2, col3 = st.columns(3)
            with col1:
                client_name = st.text_input("Client Name *")
            with col2:
                client_phone = st.text_input("Phone Number *")
            with col3:
                client_email = st.text_input("Email")

            st.divider()
            st.markdown("### 🖨️ Equipment Details (Multiple Printers Supported)")

            # Use st.session_state["temp_printers"] for the current list
            printers_list = st.session_state["temp_printers"]

            remove_flags = []
            
            # Draw each printer row (MODIFICAT: Coloane pentru 'Warranty')
            for i, p in enumerate(printers_list):
                st.markdown(f"**Printer #{i+1}**")
                # COLOANE MODIFICATE: 3 pentru detalii + 1 pentru warranty + 1 pentru remove
                colA, colB, colC, colD, colE = st.columns([1.2, 1.2, 1.2, 0.8, 0.6])
                with colA:
                    p["brand"] = st.text_input(f"Brand #{i+1} *", value=p["brand"], key=f"new_printer_brand_{i}")
                with colB:
                    p["model"] = st.text_input(f"Model #{i+1} *", value=p["model"], key=f"new_printer_model_{i}")
                with colC:
                    p["serial"] = st.text_input(f"Serial #{i+1}", value=p["serial"], key=f"new_printer_serial_{i}")
                with colD:
                    # NOU: Checkbox Warranty
                    initial_warranty = p.get("warranty", False)
                    p["warranty"] = st.checkbox(
                        "Warranty",
                        value=initial_warranty,
                        key=f"new_printer_warranty_{i}",
                        help="Check this box if the printer is received under warranty."
                    )
                with colE:
                    remove_flags.append(
                        st.checkbox("Remove", key=f"new_printer_remove_{i}")
                    )

            # Process removals and update session state
            new_printers_list = [p for i, p in enumerate(printers_list) if not remove_flags[i]]
            st.session_state["temp_printers"] = new_printers_list

            # Trecerea la un RERUN este necesară aici dacă s-a apăsat "Remove"
            # Deși acest lucru nu este garantat într-un form, checkbox-ul funcționează.

            st.divider()
            st.markdown("### 📝 Service Details")

            issue_description = st.text_area("Issue Reported *", height=150)

            colA, colB = st.columns(2)
            with colA:
                accessories = st.text_input("Accessories Received (e.g., Power cable, USB cable)")
            with colB:
                notes = st.text_area("Internal Notes (not visible to client on receipt)", height=150)

            col_dates, _ = st.columns([1.5, 3])
            with col_dates:
                date_received = st.date_input("Date Received *", value=date.today())
                date_pickup = st.date_input("Scheduled Pickup Date", value=None)

            submitted = st.form_submit_button("✅ Create Service Order", type="primary", use_container_width=True)

            if submitted:
                if not client_name or not client_phone or not issue_description:
                    st.error("❌ Please fill in all required fields (Client Name, Phone, Issue Reported).")
                    st.stop()
                
                # Check for minimum 1 printer detail
                printers_clean = []
                for p in st.session_state["temp_printers"]:
                    brand = safe_text(p.get("brand", "")).strip()
                    model = safe_text(p.get("model", "")).strip()
                    serial = safe_text(p.get("serial", "")).strip()
                    warranty = p.get("warranty", False) # NOU: Preluare stare warranty
                    if brand or model or serial:
                        printers_clean.append({
                            "brand": brand,
                            "model": model,
                            "serial": serial,
                            "warranty": warranty, # NOU: Includere warranty
                        })

                if not printers_clean:
                    st.error("❌ Please add at least one printer with Brand and Model.")
                    st.stop()
                
                # Store the cleaned list back to session state to be used after successful save
                st.session_state["temp_printers"] = printers_clean

                try:
                    # MODIFICAT: Eliminat has_warranty din apel
                    order_id = crm.create_service_order(
                        client_name, client_phone, client_email,
                        printers_clean,
                        issue_description, accessories, notes, date_received, date_pickup
                    )

                    if order_id:
                        st.session_state["last_created_order"] = order_id
                        st.session_state["pdf_downloaded"] = False # Reset flag
                        st.success(f"🎉 Service Order **{order_id}** created successfully!")

                        # Clear form/temp state for next order
                        st.session_state["temp_printers"] = [{"brand": "", "model": "", "serial": "", "warranty": False}]
                        st.rerun()

                except Exception as e:
                    st.error(f"An error occurred during save: {e}")
                    st.stop()
        # --- END OF FORM ---

        # MUTAT BUTONUL "ADD PRINTER" IN AFARA FORM-ULUI
        if st.button("➕ Add Another Printer", type="secondary"):
            # NOU: Initialize 'warranty' as False for a new printer
            st.session_state["temp_printers"].append({"brand": "", "model": "", "serial": "", "warranty": False})
            st.rerun()

        if st.session_state["last_created_order"]:
            last_order_id = st.session_state["last_created_order"]
            
            # Read the recently created order data for PDF generation
            if df_all_orders is not None and not df_all_orders.empty:
                order_latest = df_all_orders[df_all_orders['order_id'] == last_order_id].iloc[0].to_dict()
                
                st.markdown(f"### Document for Order {last_order_id}")
                
                colp1, colp2 = st.columns(2)
                with colp1:
                    st.markdown("**Initial Receipt (Dovada Predare)**")
                    pdf_init = generate_initial_receipt_pdf(order_latest, st.session_state["company_info"], logo)
                    st.download_button(
                        "⬇️ Download PDF",
                        pdf_init,
                        f"Receipt_{order_latest['order_id']}.pdf",
                        "application/pdf",
                        use_container_width=True,
                        key=f"dl_init_{order_latest['order_id']}",
                        on_click=lambda: st.session_state.update(pdf_downloaded=True, last_created_order=None)
                    )

                if st.session_state["pdf_downloaded"]:
                    st.session_state["last_created_order"] = None
                    st.session_state["pdf_downloaded"] = False

    # --- TAB 1: VIEW/SEARCH ---
    with tabs[1]:
        st.session_state["active_tab"] = 1
        st.header(tab_names[1])
        
        if not df_all_orders.empty:
            df_display = df_all_orders.copy()
            
            # Format display columns
            df_display = df_display.rename(columns={
                'order_id': 'Order ID', 
                'client_name': 'Client Name',
                'client_phone': 'Phone',
                'status': 'Status',
                'date_received': 'Received',
                'date_completed': 'Completed',
                'total_cost': 'Total Cost (RON)',
                'technician': 'Technician'
            })
            
            # Select relevant columns for display
            display_cols = ['Order ID', 'Client Name', 'Phone', 'Status', 'Received', 'Total Cost (RON)', 'Technician']
            
            # Convert cost to float and handle NaN for sum
            df_display['Total Cost (RON)'] = pd.to_numeric(df_display['Total Cost (RON)'], errors='coerce').fillna(0.0).apply(lambda x: f"{x:.2f}")

            # Filter controls
            col_search, col_status = st.columns([2, 1])
            with col_search:
                search_term = st.text_input("Search by Order ID, Client Name, or Phone", "")
            with col_status:
                selected_status = st.selectbox("Filter by Status", ["All"] + list(df_display['Status'].unique()))

            # Apply filters
            df_filtered = df_display[display_cols].copy()
            if selected_status != "All":
                df_filtered = df_filtered[df_filtered['Status'] == selected_status]

            if search_term:
                df_filtered = df_filtered[
                    df_filtered['Order ID'].str.contains(search_term, case=False, na=False) |
                    df_filtered['Client Name'].str.contains(search_term, case=False, na=False) |
                    df_filtered['Phone'].str.contains(search_term, case=False, na=False)
                ]
            
            # Display table
            st.dataframe(
                df_filtered,
                use_container_width=True,
                hide_index=True
            )
            
            st.markdown(f"**Total Orders Displayed:** {len(df_filtered)} / {len(df_all_orders)}")

        else:
            st.info("📝 No orders yet. Create a new order in the first tab.")

    # --- TAB 2: UPDATE/COMPLETE ORDER ---
    with tabs[2]:
        st.session_state["active_tab"] = 2
        st.header(tab_names[2])

        if not df_all_orders.empty:
            df_all_orders_copy = df_all_orders.copy()
            # Sort by ID (descending) and ensure string format
            order_ids = sorted([str(oid) for oid in df_all_orders_copy['order_id'].unique() if str(oid).startswith("SRV-")], reverse=True)
            
            # Keep previous selection if it's still valid
            if st.session_state["selected_order_for_update"] not in order_ids:
                 st.session_state["selected_order_for_update"] = order_ids[0] if order_ids else None

            # 1. Select Order
            selected_order_id = st.selectbox(
                "Select Order to Update",
                options=order_ids,
                index=order_ids.index(st.session_state["selected_order_for_update"]) if st.session_state["selected_order_for_update"] in order_ids else 0,
                key="update_select_box"
            )
            st.session_state["selected_order_for_update"] = selected_order_id


            if selected_order_id:
                current_order_data = df_all_orders_copy[df_all_orders_copy['order_id'] == selected_order_id].iloc[0].to_dict()
                
                st.divider()
                st.subheader(f"Updating Order: **{selected_order_id}** (Status: **{current_order_data['status']}**)")
                
                # Check if the selected order changed, if so, load printers
                state_key = f"update_printers_{selected_order_id}"
                if st.session_state["previous_selected_order"] != selected_order_id or state_key not in st.session_state:
                    st.session_state[state_key] = load_printers_from_order(current_order_data)
                    st.session_state["previous_selected_order"] = selected_order_id

                current_printers = st.session_state[state_key]

                # --- Update Form ---
                with st.container(border=True):
                    
                    st.markdown("#### ⚙️ Order Details")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        client_name = st.text_input("Client Name", value=current_order_data.get('client_name', ''), key=f"upd_client_name_{selected_order_id}")
                        client_phone = st.text_input("Phone Number", value=current_order_data.get('client_phone', ''), key=f"upd_client_phone_{selected_order_id}")
                    with col2:
                        client_email = st.text_input("Email", value=current_order_data.get('client_email', ''), key=f"upd_client_email_{selected_order_id}")
                        accessories = st.text_input("Accessories", value=current_order_data.get('accessories', ''), key=f"upd_accessories_{selected_order_id}")
                        
                    st.text_area("Initial Issue Reported", value=current_order_data.get('issue_description', ''), disabled=True, height=50)

                    st.divider()
                    st.markdown("#### 🖨️ Equipment Details")

                    # Display and allow editing of multiple printers (MODIFICAT: Coloane pentru 'Warranty')
                    remove_flags = []
                    for i, p in enumerate(current_printers):
                        st.markdown(f"**Printer #{i+1}**")
                        # COLOANE MODIFICATE: 3 pentru detalii + 1 pentru warranty + 1 pentru remove
                        colA, colB, colC, colD, colE = st.columns([1.2, 1.2, 1.2, 0.8, 0.6])
                        with colA:
                            p["brand"] = st.text_input(f"Brand #{i+1}", value=p["brand"], key=f"upd_brand_{selected_order_id}_{i}")
                        with colB:
                            p["model"] = st.text_input(f"Model #{i+1}", value=p["model"], key=f"upd_model_{selected_order_id}_{i}")
                        with colC:
                            p["serial"] = st.text_input(f"Serial #{i+1}", value=p["serial"], key=f"upd_serial_{selected_order_id}_{i}")
                        with colD:
                            # NOU: Checkbox Warranty
                            initial_warranty = p.get("warranty", False)
                            p["warranty"] = st.checkbox(
                                "Warranty",
                                value=initial_warranty,
                                key=f"upd_warranty_printer_{selected_order_id}_{i}",
                                help="Check this box if the printer is under warranty."
                            )
                        with colE:
                            remove_flags.append(
                                st.checkbox("Remove", key=f"upd_remove_printer_{selected_order_id}_{i}")
                            )
                    
                    # Process removals and update session state
                    new_printers_list = [p for i, p in enumerate(current_printers) if not remove_flags[i]]
                    st.session_state[state_key] = new_printers_list
                    
                    if st.button("➕ Add New Printer to Order", key=f"add_upd_printer_{selected_order_id}", type="secondary"):
                        # NOU: Initialize 'warranty' as False for a new printer
                        st.session_state[state_key].append({"brand": "", "model": "", "serial": "", "warranty": False})
                        st.rerun()

                    st.divider()
                    st.markdown("#### 🔧 Repair & Cost Details")
                    
                    col_status, col_tech = st.columns(2)
                    with col_status:
                        new_status = st.selectbox(
                            "Status *",
                            options=["Received", "In Progress", "Awaiting Parts", "Completed", "Picked Up", "Canceled"],
                            index=["Received", "In Progress", "Awaiting Parts", "Completed", "Picked Up", "Canceled"].index(current_order_data.get('status', 'Received')),
                            key=f"upd_status_{selected_order_id}"
                        )
                    with col_tech:
                        technician = st.text_input("Technician", value=current_order_data.get('technician', ''), key=f"upd_technician_{selected_order_id}")
                    
                    repair_details = st.text_area("Repair Details (visible on completion receipt)", value=current_order_data.get('repair_details', ''), height=100, key=f"upd_repair_details_{selected_order_id}")
                    parts_used = st.text_area("Parts Used (visible on completion receipt)", value=current_order_data.get('parts_used', ''), height=100, key=f"upd_parts_used_{selected_order_id}")
                    notes = st.text_area("Internal Notes", value=current_order_data.get('notes', ''), height=100, key=f"upd_notes_{selected_order_id}")

                    st.markdown("---")
                    col_cost1, col_cost2, col_cost3, col_cost4 = st.columns(4)
                    with col_cost1:
                        labor_cost = st.number_input("Labor Cost (RON)", value=safe_float(current_order_data.get('labor_cost', 0.0)), min_value=0.0, step=1.0, key=f"upd_labor_cost_{selected_order_id}")
                    with col_cost2:
                        parts_cost = st.number_input("Parts Cost (RON)", value=safe_float(current_order_data.get('parts_cost', 0.0)), min_value=0.0, step=1.0, key=f"upd_parts_cost_{selected_order_id}")
                    with col_cost3:
                        # Auto-calculate total cost
                        calculated_total = labor_cost + parts_cost
                        total_cost = st.number_input("Total Cost (RON) *", value=safe_float(current_order_data.get('total_cost', calculated_total)), min_value=0.0, step=1.0, key=f"upd_total_cost_{selected_order_id}")
                        if total_cost != calculated_total:
                             st.caption(f"Calculated: {calculated_total:.2f} RON")

                    with col_cost4:
                        date_received_val = safe_text(current_order_data.get('date_received', ''))
                        date_received_display = datetime.strptime(date_received_val, "%Y-%m-%d").date() if date_received_val else None
                        
                        date_picked_up_current = current_order_data.get('date_picked_up')
                        date_picked_up_value = datetime.strptime(date_picked_up_current, "%Y-%m-%d").date() if date_picked_up_current else None
                        
                        date_picked_up = st.date_input("Date Picked Up", value=date_picked_up_value, key=f"upd_date_picked_up_{selected_order_id}")


                if st.button("💾 Update Order", type="primary", use_container_width=True):
                    
                    # Re-validate essential data
                    if not client_name or not client_phone:
                        st.error("❌ Client Name and Phone cannot be empty.")
                        st.stop()
                    
                    # Clean printers list before saving
                    printers_clean = []
                    for p in st.session_state[state_key]:
                        brand = safe_text(p.get("brand", "")).strip()
                        model = safe_text(p.get("model", "")).strip()
                        serial = safe_text(p.get("serial", "")).strip()
                        warranty = p.get("warranty", False) # NOU: Preluare stare warranty
                        if brand or model or serial:
                            printers_clean.append({
                                "brand": brand,
                                "model": model,
                                "serial": serial,
                                "warranty": warranty, # NOU: Includere warranty
                            })

                    printers_json = json.dumps(printers_clean, ensure_ascii=False)

                    updates = {
                        "client_name": client_name,
                        "client_phone": client_phone,
                        "client_email": client_email,
                        "printer_brand": printers_clean[0].get("brand", "") if printers_clean else "",
                        "printer_model": printers_clean[0].get("model", "") if printers_clean else "",
                        "printer_serial": printers_clean[0].get("serial", "") if printers_clean else "",
                        "printers_json": printers_json,
                        "accessories": accessories,
                        "notes": notes,
                        "status": new_status,
                        "technician": technician,
                        "repair_details": repair_details,
                        "parts_used": parts_used,
                        "labor_cost": labor_cost,
                        "parts_cost": parts_cost,
                        "total_cost": total_cost,
                        "date_picked_up": date_picked_up.strftime("%Y-%m-%d") if date_picked_up else "",
                        "date_completed": date.today().strftime("%Y-%m-%d") if new_status == "Completed" and not current_order_data.get('date_completed') else current_order_data.get('date_completed', ''),
                    }

                    if crm.update_service_order(selected_order_id, updates):
                        st.success(f"Order **{selected_order_id}** updated successfully!")
                        st.session_state["previous_selected_order"] = None # Force printer reload on next view
                        st.rerun()
                    else:
                        st.error("Error updating order.")

                # Documents Section
                st.divider()
                st.markdown("#### 📄 Order Documents")
                order_latest = df_all_orders[df_all_orders['order_id'] == selected_order_id].iloc[0].to_dict()
                
                colp1, colp2 = st.columns(2)
                with colp1:
                    st.markdown("**Initial Receipt (Dovada Predare)**")
                    pdf_init = generate_initial_receipt_pdf(order_latest, st.session_state["company_info"], logo)
                    st.download_button(
                        "📄 Download Initial",
                        pdf_init,
                        f"Receipt_{order_latest['order_id']}.pdf",
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
    with tabs[3]:
        st.session_state["active_tab"] = 3
        st.header(tab_names[3])
        df = df_all_orders
        if not df.empty:
            # Convert cost to numeric for calculations
            df['total_cost'] = pd.to_numeric(df['total_cost'], errors='coerce').fillna(0.0)

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
