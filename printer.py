def generate_initial_receipt_pdf(order, company_info, logo_image=None):
    buffer = io.BytesIO()
    width, height = 210*mm, 148.5*mm
    c = canvas.Canvas(buffer, pagesize=(width, height))
    
    # Logo
    if logo_image:
        try:
            logo = Image.open(logo_image)
            logo.thumbnail((150,95), Image.Resampling.LANCZOS)
            logo_buffer = io.BytesIO()
            logo.save(logo_buffer, format='PNG')
            logo_buffer.seek(0)
            c.drawImage(ImageReader(logo_buffer), 10*mm, height-30*mm, width=40*mm, height=25*mm, preserveAspectRatio=True, mask='auto')
        except:
            c.setFillColor(colors.HexColor('#f0f0f0'))
            c.rect(10*mm, height-30*mm, 40*mm, 25*mm, fill=1, stroke=1)
            c.setFillColor(colors.black)
            c.setFont("Helvetica-Bold", 10)
            c.drawCentredString(10*mm+20*mm, height-17.5*mm, "[LOGO]")
    else:
        c.setFillColor(colors.HexColor('#f0f0f0'))
        c.rect(10*mm, height-30*mm, 40*mm, 25*mm, fill=1, stroke=1)
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(10*mm+20*mm, height-17.5*mm, "[LOGO]")
    
    # Company info - left side
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(10*mm, height-35*mm, remove_diacritics(company_info.get('company_name','')))
    c.setFont("Helvetica", 8)
    y_pos = height-40*mm
    c.drawString(10*mm, y_pos, remove_diacritics(company_info.get('company_address','')))
    y_pos -= 3.5*mm
    c.drawString(10*mm, y_pos, f"CUI: {company_info.get('cui','')} | Reg.Com: {company_info.get('reg_com','')}")
    y_pos -= 3.5*mm
    c.drawString(10*mm, y_pos, f"Tel: {company_info.get('phone','')} | {company_info.get('email','')}")
    
    # Client info - right side
    c.setFont("Helvetica-Bold", 9)
    c.drawString(120*mm, height-15*mm, "CLIENT")
    c.setFont("Helvetica", 8)
    y_pos = height-20*mm
    c.drawString(120*mm, y_pos, f"Nume: {remove_diacritics(safe_text(order.get('client_name','')))}")
    y_pos -= 3.5*mm
    c.drawString(120*mm, y_pos, f"Tel: {safe_text(order.get('client_phone',''))}")
    
    # Title
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(105*mm, height-55*mm, "BON PREDARE ECHIPAMENT IN SERVICE")
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(colors.HexColor('#0066cc'))
    c.drawCentredString(105*mm, height-62*mm, f"Nr. Comanda: {safe_text(order.get('order_id',''))}")
    c.setFillColor(colors.black)
    
    # Equipment details
    y_pos = height-72*mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(10*mm, y_pos, "DETALII ECHIPAMENT:")
    y_pos -= 5*mm
    c.setFont("Helvetica", 8)
    
    # Printer brand and model
    printer_info = f"{remove_diacritics(safe_text(order.get('printer_brand','')))} {remove_diacritics(safe_text(order.get('printer_model','')))}"
    c.drawString(10*mm, y_pos, f"Imprimanta: {printer_info}")
    y_pos -= 4*mm
    
    # Serial
    serial = safe_text(order.get('printer_serial','N/A'))
    c.drawString(10*mm, y_pos, f"Serie: {serial}")
    y_pos -= 4*mm
    
    # Date received
    c.drawString(10*mm, y_pos, f"Data predarii: {safe_text(order.get('date_received',''))}")
    y_pos -= 4*mm
    
    # Accessories
    accessories = safe_text(order.get('accessories',''))
    if accessories and accessories.strip():
        c.drawString(10*mm, y_pos, f"Accesorii: {remove_diacritics(accessories)}")
        y_pos -= 4*mm
        
    # --- NEW: WARRANTY CHECK ---
    # Verificăm dacă există câmpul 'has_warranty' și dacă e True
    has_warranty = order.get('has_warranty')
    # Poate veni ca boolean True/False sau string "TRUE"/"FALSE" din Sheets
    is_warranty = str(has_warranty).lower() in ['true', '1', 'yes', 'da']
    warranty_text = "DA" if is_warranty else "NU"
    
    c.setFont("Helvetica-Bold", 8)
    c.drawString(10*mm, y_pos, f"GARANTIE: {warranty_text}")
    c.setFont("Helvetica", 8)
    y_pos -= 4*mm
    # ---------------------------
    
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
    y_pos = 25*mm
    c.rect(10*mm, y_pos, 85*mm, 20*mm)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(12*mm, y_pos+17*mm, "OPERATOR SERVICE")
    c.setFont("Helvetica", 7)
    c.drawString(12*mm, y_pos+2*mm, "Semnatura si Stampila")
    
    c.rect(115*mm, y_pos, 85*mm, 20*mm)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(117*mm, y_pos+17*mm, "CLIENT")
    c.setFont("Helvetica", 7)
    c.drawString(117*mm, y_pos+13*mm, f"Nume: {remove_diacritics(safe_text(order.get('client_name','')))}")
    c.drawString(117*mm, y_pos+2*mm, "Semnatura")
    
    # Footer
    c.setFont("Helvetica", 6)
    c.drawCentredString(105*mm, 3*mm, "Acest document constituie dovada predarii echipamentului in service.")
    c.setDash(3, 3)
    c.line(5*mm, 1*mm, 205*mm, 1*mm)
    
    c.save()
    buffer.seek(0)
    return buffer
