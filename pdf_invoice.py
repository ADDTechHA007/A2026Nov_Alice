"""Read the column-based QuickBooks Invoice PDF layout; reject uncertain totals."""
import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

MONEY = r"(?:\$\s*)?([\d,]+\.\d{2})"


def rows_from_words(words):
    rows = []
    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if not rows or abs(rows[-1][0]["top"] - word["top"]) > 3:
            rows.append([word])
        else:
            rows[-1].append(word)
    return [sorted(row, key=lambda w: w["x0"]) for row in rows]


def text(row):
    return " ".join(w["text"] for w in row)


def block(rows, top, bottom, left, right):
    return "\n".join(text([w for w in row if left <= w["x0"] < right])
                     for row in rows if top < row[0]["top"] < bottom
                     and any(left <= w["x0"] < right for w in row)).strip()


def decimal(value):
    try:
        result = Decimal(value.replace(",", "").replace("$", "").strip())
        if not result.is_finite() or result < 0:
            raise InvalidOperation()
        return result
    except (InvalidOperation, AttributeError):
        raise ValueError("PDF 中有无法核对的数量或金额，请改用产品明细 XLS / CSV。")


def pdf_date(raw, order):
    if not raw:
        return "", False
    raw = raw.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            return datetime.strptime(raw, "%Y-%m-%d").date().isoformat(), False
        if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", raw):
            first, second, _ = map(int, raw.split("/"))
            if not order and first <= 12 and second <= 12 and first != second:
                return "", True
            fmt = "%d/%m/%Y" if order == "dmy" or not order and first > 12 else "%m/%d/%Y"
            return datetime.strptime(raw, fmt).date().isoformat(), False
        for fmt in ("%b %d, %Y", "%B %d, %Y"):
            try:
                return datetime.strptime(raw, fmt).date().isoformat(), False
            except ValueError:
                pass
    except ValueError:
        pass
    raise ValueError(f"PDF 日期 {raw!r} 无法按所选日期格式读取，请核对原件。")


def header_fields(rows, header, bottom, labels, width):
    starts = [(w["x0"], labels[w["text"].upper()]) for w in header if w["text"].upper() in labels]
    result = {}
    for n, (left, key) in enumerate(starts):
        right = starts[n + 1][0] - 2 if n + 1 < len(starts) else width
        result[key] = block(rows, header[0]["top"] + 3, bottom, left - 2, right)
    return result


def parse_pdf(raw, date_order=""):
    if date_order not in ("", "dmy", "mdy"):
        raise ValueError("PDF 日期格式无效。")
    try:
        import pdfplumber
    except ImportError:
        raise ValueError("尚未安装 PDF 读取依赖，请安装 requirements.txt 后重启工作台。")
    try:
        document = pdfplumber.open(io.BytesIO(raw))
    except Exception:
        raise ValueError("无法打开 PDF；请提供未加密的 QuickBooks 原始导出 PDF。")
    lines, totals, tax_rows, warnings, extracted = [], {}, [], [], {}
    with document:
        if not 1 <= len(document.pages) <= 10:
            raise ValueError("一次仅支持1至10页、同一张 Invoice 的 PDF。")
        full_text = []
        for page_number, page in enumerate(document.pages, 1):
            rows = rows_from_words(page.extract_words())
            if not rows:
                raise ValueError("PDF 没有可读取的文字，可能是扫描件。请从 QuickBooks 下载原始 PDF；本版不做图片 OCR。")
            full_text.append(page.extract_text() or "")
            candidates = [row for row in rows if {"DESCRIPTION", "QTY", "RATE", "AMOUNT"}.issubset({w["text"].upper() for w in row})]
            if len(candidates) != 1:
                raise ValueError(f"PDF 第{page_number}页未识别到完整产品表头，暂不支持此版式，请改用 XLS / CSV。")
            header = candidates[0]
            positions = {w["text"].upper(): w for w in header}
            if "TAX" not in positions:
                raise ValueError("PDF 产品表缺少 TAX 列，暂不支持此版式。")
            desc_left = positions["DESCRIPTION"]["x0"] - 2
            qty_left = positions["QTY"]["x0"] - 18
            rate_left = (positions["QTY"]["x1"] + positions["RATE"]["x0"]) / 2
            tax_left = (positions["RATE"]["x1"] + positions["TAX"]["x0"]) / 2
            amount_left = (positions["TAX"]["x1"] + positions["AMOUNT"]["x0"]) / 2
            summary = [row for row in rows if any(w["text"].upper() == "SUBTOTAL" and w["x0"] > page.width * .45 for w in row)]
            end = summary[0][0]["top"] - 2 if summary else page.height - 45

            # Invoice and contact fields are read only from the invoice header, never seller's footer.
            inv_headers = [row for row in rows if "INVOICE" in {w["text"].upper() for w in row} and "DATE" in {w["text"].upper() for w in row}]
            if inv_headers:
                inv_header = inv_headers[0]
                shipping = next((row for row in rows if inv_header[0]["top"] < row[0]["top"] < header[0]["top"] and "TRACKING" in {w["text"].upper() for w in row}), None)
                fields = header_fields(rows, inv_header, shipping[0]["top"] if shipping else header[0]["top"],
                                       {"INVOICE": "invoice", "DATE": "invoice_date_raw", "TOTAL": "header_total_due", "TERMS": "terms", "ENCLOSED": "enclosed", "DUE": "_due"}, page.width)
                # DUE in TOTAL DUE belongs to the amount label, not a payment date column.
                if "_due" in fields:
                    fields.pop("_due")
                if extracted.get("invoice") and fields.get("invoice") != extracted["invoice"]:
                    raise ValueError("PDF 包含多个 Invoice 编号，请每次只导入一张发票。")
                if not extracted:
                    extracted.update(fields)
                    bill_header = next((row for row in rows if row[0]["top"] < inv_header[0]["top"] and "BILL" in {w["text"].upper() for w in row}), None)
                    if bill_header:
                        bill = next(w for w in bill_header if w["text"].upper() == "BILL")
                        ship = next((w for w in bill_header if w["text"].upper() == "SHIP"), None)
                        extracted["bill_to"] = block(rows, bill_header[0]["top"] + 3, inv_header[0]["top"] - 3, bill["x0"] - 2, ship["x0"] - 4 if ship else page.width * .55)
                        extracted["ship_to"] = block(rows, bill_header[0]["top"] + 3, inv_header[0]["top"] - 3, ship["x0"] - 2, page.width) if ship else ""
                        bill_lines = extracted["bill_to"].splitlines()
                        extracted["customer"] = bill_lines[1] if len(bill_lines) >= 4 else bill_lines[0] if bill_lines else ""
                        extracted["contact"] = bill_lines[0] if len(bill_lines) >= 4 else ""
                    if shipping:
                        extracted.update(header_fields(rows, shipping, header[0]["top"], {"SHIP": "_ship", "TRACKING": "tracking_no", "REP": "rep", "PO": "po"}, page.width))
                        ships = [w for w in shipping if w["text"].upper() == "SHIP"]
                        if len(ships) == 2:
                            extracted["shipping_date_raw"] = block(rows, shipping[0]["top"] + 3, header[0]["top"], ships[0]["x0"] - 2, ships[1]["x0"] - 2)
                            tracking = next(w for w in shipping if w["text"].upper() == "TRACKING")
                            extracted["ship_via"] = block(rows, shipping[0]["top"] + 3, header[0]["top"], ships[1]["x0"] - 2, tracking["x0"] - 2)
                        extracted.pop("_ship", None)

            current = None
            for row in rows:
                y = row[0]["top"]
                if not header[0]["top"] + 3 < y < end:
                    continue
                col = lambda left, right: text([w for w in row if left <= w["x0"] < right])
                qty, rate, amount = col(qty_left, rate_left), col(rate_left, tax_left), col(amount_left, page.width)
                description, product = col(desc_left, qty_left), col(0, desc_left)
                if qty or rate or amount:
                    if not qty or not rate or not amount or not description:
                        raise ValueError(f"PDF 第{page_number}页有未能完整识别的产品行，请改用 XLS / CSV 核对。")
                    q, p, a = decimal(qty), decimal(rate), decimal(amount)
                    if not 0 < q <= 10000000 or q != q.to_integral_value() or (q * p).quantize(Decimal('.01'), rounding=ROUND_HALF_UP) != a:
                        raise ValueError("PDF 产品数量 × 单价与行金额不一致，请核对原件，不导入不完整数据。")
                    current = {"source_row": len(lines) + 1, "source_page": page_number, "product_service": product,
                               "name": description, "spec": description, "qty": int(q), "sales_rate": str(p),
                               "sales_amount": str(a.quantize(Decimal('.01'))), "tax_code": col(tax_left, amount_left)}
                    lines.append(current)
                elif current and (description or product):
                    if re.fullmatch(r"(?:Page\s+)?\d+\s+(?:of|/)\s+\d+", description or product, re.I):
                        continue
                    if description:
                        current["spec"] += "\n" + description
                    if product:
                        current["product_service"] += " " + product
                elif description or product:
                    raise ValueError("PDF 产品跨页或说明行无法明确归属，请改用 XLS / CSV，避免遗漏规格。")

            if summary:
                for row in rows:
                    if row[0]["top"] < end:
                        continue
                    right = text([w for w in row if w["x0"] >= page.width * .5])
                    match = re.fullmatch(r"(SUBTOTAL|TOTAL|BALANCE DUE)\s+" + MONEY, right, re.I)
                    if match:
                        key = {"SUBTOTAL": "subtotal", "TOTAL": "total", "BALANCE DUE": "balance_due"}[match[1].upper()]
                        if key in totals:
                            raise ValueError("PDF 有重复合计区域，可能包含多张发票，请拆分后导入。")
                        totals[key] = str(decimal(match[2]).quantize(Decimal('.01')))
                    tax = re.fullmatch(r"(.+?)\s+@\s*([\d.]+)%\s+" + MONEY, right)
                    if tax:
                        tax_rows.append({"label": tax[1], "rate": tax[2], "amount": str(decimal(tax[3]).quantize(Decimal('.01')))})

    if not extracted.get("invoice") or not 1 <= len(lines) <= 50 or not {"subtotal", "total"}.issubset(totals):
        raise ValueError("PDF 未能完整识别发票编号、产品和合计，请使用同版式原始 PDF 或 XLS / CSV。")
    subtotal = sum(Decimal(line["sales_amount"]) for line in lines)
    tax_amount = sum(Decimal(row["amount"]) for row in tax_rows)
    if subtotal != Decimal(totals["subtotal"]) or subtotal + tax_amount != Decimal(totals["total"]):
        raise ValueError("PDF 明细、小计、税额和总额未能核对一致，可能含折扣、运费或其他版式，请改用 XLS / CSV 核对。")
    extracted.update(totals)
    extracted["tax_amount"] = str(tax_amount.quantize(Decimal('.01')))
    extracted["tax_rows"] = tax_rows
    extracted["tax_rate"] = tax_rows[0]["rate"] if len(tax_rows) == 1 and (subtotal * Decimal(tax_rows[0]["rate"]) / 100).quantize(Decimal('.01'), rounding=ROUND_HALF_UP) == tax_amount else ""
    extracted["tax_label"] = " + ".join(row["label"] + " @ " + row["rate"] + "%" for row in tax_rows) or "PDF 税额为0（请核对）"
    combined = "\n".join(full_text)
    currencies = set(re.findall(r"\b(?:CAD|USD|CNY)\b", combined))
    extracted["currency"] = next(iter(currencies)) if len(currencies) == 1 else ""
    extracted["date_format_required"] = False
    for key in ("invoice_date", "shipping_date"):
        parsed_date, ambiguous = pdf_date(extracted.get(key + "_raw", ""), date_order)
        extracted[key] = parsed_date
        extracted["date_format_required"] |= ambiguous
    extracted["payment_due"] = ""
    warnings.append("客户名称是从 Bill to 识别的候选值，请与完整抬头核对。")
    if extracted["date_format_required"]:
        warnings.append("日期有日/月歧义，请选择 PDF 日期格式后重新读取；不要根据 Invoice 编号推算日期。")
    if not extracted["currency"]:
        warnings.append("PDF 未明确标注币种；$ 不能区分 CAD / USD，请确认后填写。")
    warnings.append("未识别到付款到期日；TOTAL DUE 是应付金额，SHIP DATE 是发货日期，均不作交货要求。")
    for n, line in enumerate(lines, 1):
        for q in re.findall(r"\bQty\s*:\s*([\d,]+)", line["spec"], re.I):
            if int(q.replace(",", "")) != line["qty"]:
                warnings.append(f"第{n}项数量栏为 {line['qty']:,}，描述 Qty 为 {int(q.replace(',', '')):,}，请核对；按数量栏导入并保留描述。")
    extracted["warnings"] = warnings
    return {"sheet": f"PDF / {len(document.pages)}页", "lines": lines, "subtotal": totals["subtotal"],
            "format": "pdf", "extracted": extracted, "warnings": warnings}
