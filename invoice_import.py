"""Read QBO line exports. Import preserves source data and never infers production type."""
import base64
import csv
import hashlib
import io
import json
import mimetypes
import sys
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

HEADERS = ["PRODUCT/SERVICE", "DESCRIPTION", "QUANTITY", "RATE", "AMOUNT", "SALES TAX"]


def decode_file(file):
    name = Path(str(file.get("name", "")).replace("\\", "/")).name[:200]
    try:
        data = base64.b64decode(file.get("data", ""), validate=True)
    except Exception:
        raise ValueError("文件数据无效，请重新选择文件。")
    if not name or not 0 < len(data) <= 10 * 1024 * 1024:
        raise ValueError("每个来源文件须为 1 字节至 10MB。")
    return name, data


def parse_export(file):
    name, raw = decode_file(file)
    ext = Path(name).suffix.lower()
    if ext == ".xls":
        sys.path.insert(0, str(Path(__file__).parent / ".read-deps"))
        try:
            import xlrd
        except ImportError:
            raise ValueError("此电脑尚未安装 XLS 读取依赖 xlrd，请改用 CSV 导出。")
        try:
            workbook = xlrd.open_workbook(file_contents=raw)
            sheets = [s for s in workbook.sheets() if s.nrows]
            matches = [s for s in sheets if [str(v).strip().upper() for v in s.row_values(0)[:6]] == HEADERS]
            if len(matches) != 1:
                raise ValueError("请提供含六列表头的单一产品明细表。")
            sheet = matches[0]
            rows = [sheet.row_values(r) for r in range(sheet.nrows)]
            sheet_name = sheet.name
        except ValueError:
            raise
        except Exception:
            raise ValueError("无法读取 XLS 文件，请使用 QuickBooks 产品明细导出，或另存为 CSV。")
    elif ext == ".csv":
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ValueError("CSV 请使用 UTF-8 编码。")
        rows, sheet_name = list(csv.reader(io.StringIO(content))), "CSV"
    else:
        raise ValueError("本版支持 QuickBooks 产品明细 .xls 或 UTF-8 .csv 文件。")
    if not rows or [str(v).strip().upper() for v in rows[0][:6]] != HEADERS:
        raise ValueError("表头应为 PRODUCT/SERVICE、DESCRIPTION、QUANTITY、RATE、AMOUNT、SALES TAX。")
    lines = []
    for n, row in enumerate(rows[1:], 2):
        if not any(str(v).strip() for v in row):
            continue
        if len(row) < 6:
            raise ValueError(f"第{n}行少于六列。")
        product, spec, qty, rate, amount, tax = [str(v).strip() for v in row[:6]]
        try:
            quantity, price, value = [Decimal(v.replace(",", "")) for v in [qty, rate, amount]]
            if not all(v.is_finite() for v in [quantity, price, value]):
                raise InvalidOperation()
            if not 0 < quantity <= 10000000 or quantity != quantity.to_integral_value() or price < 0 or value < 0:
                raise InvalidOperation()
        except (InvalidOperation, ValueError):
            raise ValueError(f"第{n}行数量须为正整数，售价及金额须为非负数字。")
        if not product or not spec:
            raise ValueError(f"第{n}行缺少产品或说明。")
        if (quantity * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) != value.quantize(Decimal("0.01")):
            raise ValueError(f"第{n}行数量 × 销售单价与金额不一致，请核实折扣等情况。")
        lines.append({"source_row": n, "product_service": product, "name": spec.splitlines()[0],
                      "spec": spec, "qty": int(quantity), "sales_rate": str(price),
                      "sales_amount": str(value.quantize(Decimal("0.01"))), "tax_code": tax})
    if not 1 <= len(lines) <= 50:
        raise ValueError("每次可导入1至50项产品。")
    return {"name": name, "sheet": sheet_name, "lines": lines,
            "subtotal": str(sum(Decimal(i["sales_amount"]) for i in lines)),
            "sha256": hashlib.sha256(raw).hexdigest()}


def save_invoice(db, payload, app):
    app.check_role(payload["actor"], ["销售", "财务"])
    invoice, customer = app.clean(payload.get("invoice"), 100), app.clean(payload.get("customer"), 200)
    if not invoice or not customer:
        raise ValueError("请补充 Invoice 编号及客户名称；产品导出文件通常不含这两项。")
    if db.execute("SELECT 1 FROM orders WHERE invoice=?", (invoice,)).fetchone():
        raise ValueError("这个 Invoice 已有档案，请打开原档案，勿重复导入。")
    parsed = parse_export(payload.get("file", {}))
    invoice_date = app.valid_date(payload.get("invoice_date"), required=False)
    payment_due = app.valid_date(payload.get("payment_due"), required=False)
    currency = app.clean(payload.get("currency"))
    if currency not in ["", "CAD", "USD", "CNY"]:
        raise ValueError("币种无效。")
    rate_text = app.clean(payload.get("tax_rate"))
    rate = tax = total = None
    if rate_text:
        try:
            rate = Decimal(rate_text) / 100
            if not rate.is_finite() or not 0 <= rate <= 1:
                raise InvalidOperation()
        except InvalidOperation:
            raise ValueError("税率应为0至100的数字，未知可留空。")
        tax = (Decimal(parsed["subtotal"]) * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total = Decimal(parsed["subtotal"]) + tax
    metadata = {
        "kind": "user-import", "invoice_date": invoice_date, "payment_due": payment_due,
        "customer_email": "", "contact": "", "bill_to": "", "ship_to": "", "currency": currency or None,
        "currency_note": "销售币种：" + currency if currency else "销售币种待确认",
        "subtotal": parsed["subtotal"], "tax_rate": str(rate) if rate is not None else None,
        "tax_amount": str(tax) if tax is not None else None, "total": str(total) if total is not None else None,
        "tax_label": ("导入时填写税率 " + rate_text + "%") if rate is not None else "税率待确认",
        "snapshot_balance_due": None, "terms_visible": "", "terms_complete": False,
        "route_basis": "制作类型由销售逐项补充，导入不根据名称、SKU或 In Stock 自动推断。",
        "pending": ["销售负责人和每项产品制作类型待补充", "交货日期、成本、库存及实际付款状态另行确认"],
        "reconciliation": [f"第{i['source_row']}行：{i['qty']} × {i['sales_rate']} = {i['sales_amount']}" for i in parsed["lines"]],
        "provenance": {"lines": parsed["name"] + " / " + parsed["sheet"], "customer_and_dates": "导入表单人工填写；不会将付款到期日写成交货日"},
        "lines": parsed["lines"], "imported_at": app.now(), "workflow_policy": "sales-production-type-v2"
    }
    files = [payload["file"], *payload.get("attachments", [])]
    if len(files) > 6:
        raise ValueError("可附最多5个额外来源文件。")
    sources = []
    for f in files:
        name, raw = decode_file(f)
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        sources.append((name, raw, mime, hashlib.sha256(raw).hexdigest()))
    if sum(len(s[1]) for s in sources) > 20 * 1024 * 1024:
        raise ValueError("来源文件合计不能超过20MB。")
    oid = app.uid()
    db.execute("INSERT INTO orders VALUES(?,?,?,?,?,?)", (oid, invoice, customer, "待确认", "", app.now()))
    db.execute("INSERT INTO order_details VALUES(?,?)", (oid, json.dumps(metadata, ensure_ascii=False)))
    for n, line in enumerate(parsed["lines"], 1):
        iid = app.uid()
        db.execute("INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (iid, oid, n, line["name"], line["qty"], app.UNCLASSIFIED, line["spec"], "", "", 0, "CAD", "", "制作类型待补充。", 0, 1, app.now()))
        db.execute("INSERT INTO invoice_lines VALUES(?,?,?,?,?,?)", (iid, line["product_service"], line["sales_rate"], line["sales_amount"], line["tax_code"], line["source_row"]))
        app.event(db, oid, iid, payload["actor"], "导入 Invoice 产品", "制作类型留空，交销售补充。", {"invoice_line": line, "source": metadata["provenance"]["lines"]})
    for name, raw, mime, digest in sources:
        db.execute("INSERT INTO order_documents VALUES(?,?,?,?,?,?,?,?,?)", (app.uid(), oid, name, mime, "Invoice 导入来源", raw, digest, payload["actor"], app.now()))
    app.event(db, oid, None, payload["actor"], "导入 Invoice", f"{invoice} · {len(parsed['lines'])}项产品，制作类型待补充。", metadata)
    return {"order_id": oid, "message": "Invoice 已导入，所有产品交销售补充制作类型。"}
