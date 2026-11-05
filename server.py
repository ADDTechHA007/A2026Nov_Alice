"""Local order review prototype. Python standard library only; no external email sending."""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import io
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from email.message import EmailMessage
from email import policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "workbench.sqlite3"
ROLES = ["销售", "审核", "老板", "跟单", "财务", "仓库", "物流"]
UNCLASSIFIED = "制作类型待补充"
TEST_REVIEWER_FULL_ACCESS = True
APPROVAL_BASE_URL = "http://127.0.0.1:8766"
PUBLIC_DEMO = False
EPHEMERAL_STORAGE = False
PRODUCTION_TYPES = ["国内定制", "本地直发", "本地加工"]
FLOWS = {
    UNCLASSIFIED: [(UNCLASSIFIED, "销售")],
    "国内定制": [("待补资料", "销售"), ("财务审核", "审核"), ("老板审批", "老板"),
               ("待下单", "跟单"), ("等工厂确认", "跟单"), ("生产中", "跟单"),
               ("待海运", "物流"), ("海运中", "物流"), ("已完成", "")],
    "本地直发": [("库存预留", "仓库"), ("待发货", "仓库"), ("已完成", "")],
    "本地加工": [("待补资料", "销售"), ("财务审核", "审核"), ("老板审批", "老板"),
               ("待送加工", "仓库"), ("加工中", "跟单"), ("待发货", "仓库"), ("已完成", "")],
}
CATEGORIES = ["图稿/规格", "工厂报价", "加工说明", "工厂确认", "付款凭证", "运输单据", "出库凭证", "其他"]
APPROVAL_CATEGORIES = ["图稿/规格", "工厂报价", "加工说明"]
SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
 id TEXT PRIMARY KEY, invoice TEXT NOT NULL UNIQUE, customer TEXT NOT NULL, sales TEXT NOT NULL,
 due TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS items (
 id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id), line_no INTEGER NOT NULL,
 name TEXT NOT NULL, qty INTEGER NOT NULL, route TEXT NOT NULL, spec TEXT NOT NULL DEFAULT '',
 supplier TEXT NOT NULL DEFAULT '', recipient TEXT NOT NULL DEFAULT '', unit_cost REAL NOT NULL DEFAULT 0,
 currency TEXT NOT NULL DEFAULT 'CAD', due TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
 stage INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1, updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents (
 id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id), item_id TEXT NOT NULL REFERENCES items(id),
 name TEXT NOT NULL, mime TEXT NOT NULL, category TEXT NOT NULL, data BLOB NOT NULL,
 actor TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT NOT NULL, item_id TEXT,
 actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL, snapshot TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages (
 id TEXT PRIMARY KEY, order_id TEXT NOT NULL, item_id TEXT NOT NULL, recipient TEXT NOT NULL,
 subject TEXT NOT NULL, body TEXT NOT NULL, snapshot TEXT NOT NULL, eml BLOB NOT NULL,
 actor TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS shipments (
 id TEXT PRIMARY KEY, order_id TEXT NOT NULL, item_id TEXT NOT NULL, qty INTEGER NOT NULL,
 vessel TEXT NOT NULL, voyage TEXT NOT NULL, bl TEXT NOT NULL, etd TEXT NOT NULL, eta TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT '海运中', created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS order_details (
 order_id TEXT PRIMARY KEY REFERENCES orders(id), metadata TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS invoice_lines (
 item_id TEXT PRIMARY KEY REFERENCES items(id), product_service TEXT NOT NULL,
 sales_rate TEXT NOT NULL, sales_amount TEXT NOT NULL, tax_code TEXT NOT NULL, source_row INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS order_documents (
 id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id), name TEXT NOT NULL,
 mime TEXT NOT NULL, category TEXT NOT NULL, data BLOB NOT NULL, sha256 TEXT NOT NULL,
 actor TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS migrations (name TEXT PRIMARY KEY, applied TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS production_details (
 item_id TEXT PRIMARY KEY REFERENCES items(id), notes TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS email_approvals (
 id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, item_id TEXT NOT NULL REFERENCES items(id),
 message_id TEXT NOT NULL REFERENCES messages(id), recipient TEXT NOT NULL, version INTEGER NOT NULL,
 stage INTEGER NOT NULL, expires TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
 summary TEXT NOT NULL, created TEXT NOT NULL, decided TEXT NOT NULL DEFAULT '', decision_note TEXT NOT NULL DEFAULT '');
"""


def uid():
    return uuid.uuid4().hex


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


@contextmanager
def connect():
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def event(db, order_id, item_id, actor, action, detail, snapshot=None):
    db.execute("INSERT INTO events(order_id,item_id,actor,action,detail,snapshot,created) VALUES(?,?,?,?,?,?,?)",
               (order_id, item_id, actor, action, detail, json.dumps(snapshot or {}, ensure_ascii=False), now()))


def seed(db):
    if db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]:
        return
    today = datetime.now().date()
    examples = [
        ("DEMO-10025", "Maple Market · 演示客户", "销售 Anna", 14, [
            ("定制棉布袋 / 海军蓝", 1000, "国内定制", 0, "38 × 42 cm，双面丝印；客户图稿 V1", "宁波示例工厂", "factory@example.com", 2.6),
            ("现货牛皮纸袋 / 中号", 200, "本地直发", 1, "中号，原色；已预留 200 个", "本地仓库", "warehouse@example.com", 0.75),
            ("库存帆布袋 / 本地印刷", 300, "本地加工", 2, "库存白色袋，单面黑色 Logo", "多伦多示例印刷商", "print@example.com", 1.2)]),
        ("DEMO-10026", "North Studio · 演示客户", "销售 Ben", 21, [
            ("定制无纺布购物袋", 2000, "国内定制", 1, "35 × 40 cm；单面印刷；图稿 V2", "上海示例工厂", "supplier@example.com", 1.45)]),
        ("DEMO-10027", "Green Retail · 演示客户", "销售 Anna", 30, [
            ("定制环保购物袋", 1000, "国内定制", 7, "40 × 45 cm；绿色；纸箱包装", "宁波示例工厂", "factory@example.com", 2.1)]),
    ]
    for inv, customer, sales, days, lines in examples:
        oid = uid()
        due = (today + timedelta(days=days)).isoformat()
        db.execute("INSERT INTO orders VALUES(?,?,?,?,?,?)", (oid, inv, customer, sales, due, now()))
        for n, (name, qty, route, stage, spec, supplier, recipient, cost) in enumerate(lines, 1):
            iid = uid()
            db.execute("INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (iid, oid, n, name, qty, route, spec, supplier, recipient, cost, "CAD", due, "演示资料，请替换为实际业务信息。", stage, 1, now()))
            event(db, oid, iid, "系统", "建立演示产品", f"{inv}-{n:02} · {name}")
            if stage >= 1 and route != "本地直发":
                cats = ["图稿/规格", "工厂报价"] if route == "国内定制" else ["图稿/规格", "加工说明"]
                for cat in cats:
                    content = f"仅供演示，不是真实业务凭证。\n订单：{inv}\n产品：{name}\n类别：{cat}\n数量：{qty}\n规格：{spec}\n采购/加工单价：{cost} CAD".encode("utf-8")
                    db.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?)", (uid(), oid, iid, cat.replace("/", "-") + "-演示.txt", "text/plain; charset=utf-8", cat, content, "系统", now()))
            if stage >= 2 and route != "本地直发":
                snapshot = dict(db.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone())
                event(db, oid, iid, "审核", "审核通过（演示）", "V1 资料审核通过，等待老板审批。", snapshot)
            if stage >= 3 and route != "本地直发":
                event(db, oid, iid, "老板", "批准（演示）", "批准 V1（仅为演示历史）。", dict(db.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()))
            if stage == 7:
                db.execute("INSERT INTO shipments VALUES(?,?,?,?,?,?,?,?,?,?,?)", (uid(), oid, iid, 600, "DEMO PACIFIC", "026E", "DEMO-BL-600", today.isoformat(), due, "海运中", now()))


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(SCHEMA)
        migrate_production_types(db)
        rename_unclassified(db)
        seed(db)


def migrate_production_types(db):
    key = "sales-production-type-v2"
    if db.execute("SELECT 1 FROM migrations WHERE name=?", (key,)).fetchone():
        return
    imported = db.execute("SELECT * FROM order_details").fetchall()
    candidates = []
    for row in imported:
        meta = json.loads(row["metadata"])
        if meta.get("kind") != "user-import" or meta.get("workflow_policy") == key:
            continue
        for item in db.execute("SELECT * FROM items WHERE order_id=? AND route='本地直发' AND stage=0", (row["order_id"],)):
            executed = db.execute("SELECT 1 FROM events WHERE item_id=? AND action IN ('完成节点','确认制作类型','老板批准','审核通过')", (item["id"],)).fetchone()
            has_ship = db.execute("SELECT 1 FROM shipments WHERE item_id=?", (item["id"],)).fetchone()
            has_mail = db.execute("SELECT 1 FROM messages WHERE item_id=?", (item["id"],)).fetchone()
            if not executed and not has_ship and not has_mail:
                candidates.append(dict(item))
    if candidates and DB_PATH == ROOT / "data" / "workbench.sqlite3":
        folder = ROOT / "data" / "backups"
        folder.mkdir(exist_ok=True)
        backup_path = folder / ("before-production-type-v2-" + now().replace(":", "-") + ".sqlite3")
        with sqlite3.connect(backup_path) as backup:
            db.backup(backup)
    for item in candidates:
        db.execute("UPDATE items SET route=?,stage=0,version=version+1,notes=?,updated=? WHERE id=?",
                   (UNCLASSIFIED, "根据新版规则，制作类型待销售补充；不再根据 In Stock 推断。", now(), item["id"]))
        event(db, item["order_id"], item["id"], "系统", "制作类型规则调整", "原先推断的本地直发已撤回，交销售逐项选择制作类型；原始来源及历史保留。", {"before": item, "rule": key})
    db.execute("INSERT INTO migrations VALUES(?,?)", (key, now()))


def rename_unclassified(db):
    for row in db.execute("SELECT id,order_id FROM items WHERE route='待销售补充'").fetchall():
        db.execute("UPDATE items SET route=?,version=version+1,updated=? WHERE id=?", (UNCLASSIFIED, now(), row["id"]))
        event(db, row["order_id"], row["id"], "系统", "明确待补充内容", "待销售补充 → 制作类型待补充；业务节点及原始资料保留。")


def item_for(db, item_id):
    row = db.execute("SELECT items.*, COALESCE(p.notes, '') AS production_notes FROM items LEFT JOIN production_details p ON p.item_id=items.id WHERE items.id=?", (item_id,)).fetchone()
    if not row:
        raise ValueError("产品记录不存在。")
    return dict(row)


def clean(value, limit=5000):
    return str(value or "").strip()[:limit]


def positive_int(value):
    try:
        n = int(value)
        if str(value).strip() != str(n) or not 0 < n <= 10_000_000:
            raise ValueError()
        return n
    except (ValueError, TypeError):
        raise ValueError("数量必须为 1 至 10000000 的整数。")


def valid_date(value, required=True):
    val = clean(value, 10)
    if not val and not required:
        return val
    try:
        return datetime.strptime(val, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise ValueError("请填写有效日期。")


def missing(db, item):
    cats = {r[0] for r in db.execute("SELECT category FROM documents WHERE item_id=?", (item["id"],))}
    needs = []
    if not item["spec"]:
        needs.append("产品规格")
    if item["route"] == UNCLASSIFIED:
        return ["制作类型（销售补充）", *needs]
    if item["route"] != "本地直发":
        if not item["supplier"]:
            needs.append("工厂/加工商")
        if not item["recipient"]:
            needs.append("收件邮箱")
        if item["unit_cost"] <= 0:
            needs.append("采购/加工单价")
        for cat in (["加工说明"] if item["route"] == "本地加工" else []):
            if cat not in cats:
                needs.append(cat)
    return needs


def optional_missing(db, item):
    categories = ["图稿/规格", "工厂报价"] if item["route"] == "国内定制" else ["图稿/规格"] if item["route"] == "本地加工" else []
    uploaded = {r[0] for r in db.execute("SELECT category FROM documents WHERE item_id=?", (item["id"],))}
    return [c for c in categories if c not in uploaded]


def approval_locked(db, item):
    return bool((item["route"] in ["国内定制", "本地加工"] and item["stage"] >= 3) or
                db.execute("SELECT 1 FROM events WHERE item_id=? AND action IN ('老板批准','批准（演示）')", (item["id"],)).fetchone())


def sales_locked(db, order_id):
    return any(approval_locked(db, r) for r in db.execute("SELECT * FROM items WHERE order_id=?", (order_id,)))


def approval_package(db, item, note):
    order = dict(db.execute("SELECT * FROM orders WHERE id=?", (item["order_id"],)).fetchone())
    target = "财务审核" if item["stage"] == 0 else "老板审批"
    subject = f"[{order['invoice']}-{item['line_no']:02}] 请{target} · {item['name']}"
    body = (f"请审核以下产品（资料 V{item['version']}）：\n"
            f"Invoice：{order['invoice']}\n客户：{order['customer']}\n销售负责人：{order['sales']}\n"
            f"产品：{item['name']}\n制作类型：{item['route']}\n数量：{item['qty']}\n"
            f"要求交货：{item['due'] or '待确认'}\n工厂 / 加工商：{item['supplier']}\n"
            f"业务收件邮箱：{item['recipient']}\n采购 / 加工单价：{item['unit_cost']} {item['currency']}\n"
            f"采购 / 加工金额：{item['qty'] * item['unit_cost']:.2f} {item['currency']}\n"
            f"规格 / 加工要求：\n{item['spec']}\n制作备注：{item['production_notes']}\n"
            f"执行备注：{item['notes']}\n提交说明：{note}\n"
            f"可选附件未附：{'、'.join(optional_missing(db, item)) or '无'}\n\n"
            "请检查本次资料及附件。本邮件为待发送草稿，生成不代表已发送或已批准。")
    docs = []
    for table, source, condition, value in [("documents", "product", "item_id", item["id"]), ("order_documents", "order", "order_id", item["order_id"])]:
        for row in db.execute(f"SELECT * FROM {table} WHERE {condition}=? ORDER BY created,id", (value,)):
            docs.append({**dict(row), "source": source, "key": source + ":" + row["id"]})
    return subject, body, docs


def create_approval_draft(db, item, actor, payload, note):
    recipient = clean(payload.get("approval_email"), 250)
    if not re.fullmatch(r"[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+", recipient):
        raise ValueError("每次提交审批都须填写有效的审批人邮箱。")
    subject, body, available = approval_package(db, item, note)
    keys = payload.get("approval_attachment_keys", [d["key"] for d in available])
    if not isinstance(keys, list) or len(keys) > 100 or any(not isinstance(k, str) for k in keys):
        raise ValueError("审批邮件附件选择无效。")
    selected = []
    by_key = {d["key"]: d for d in available}
    for key in dict.fromkeys(keys):
        if key not in by_key:
            raise ValueError("审批附件不属于当前产品或订单，请重新提交。")
        selected.append(by_key[key])
    summary = body.encode("utf-8")
    if sum(len(d["data"]) for d in selected) + len(summary) > 20 * 1024 * 1024:
        raise ValueError("审批邮件附件合计不能超过20MB，请减少所选附件。")
    mid = uid()
    request_id, token, approval_url, expiry = None, None, None, None
    summary_body = body
    if item["stage"] == 1:
        request_id, token = uid(), secrets.token_urlsafe(32)
        expiry = (datetime.now().astimezone() + timedelta(days=7)).isoformat(timespec="seconds")
        approval_url = APPROVAL_BASE_URL + "/approval.html#token=" + token
        body += f"\n\n老板邮件审批（无需登录工作台）：\n{approval_url}\n链接有效期至：{expiry}\n打开链接仅查看；须在页面明确选择批准或退回并确认后才记录结果。链接仅限指定收件人使用，请勿转发。\n本机演示：此链接只能在工作台所在电脑打开，尚未提供外网审批。"
    msg = EmailMessage(policy=policy.SMTP)
    msg["To"], msg["Subject"], msg["X-Unsent"] = recipient, subject, "1"
    msg["X-Order-Item"] = item["id"]
    msg.set_content(body)
    if approval_url:
        msg.add_alternative('<html><body><h2>订单审批请求</h2><pre style="white-space:pre-wrap">' + html.escape(summary_body) + '</pre><p><a style="display:inline-block;padding:12px 20px;background:#245a48;color:white" href="' + html.escape(approval_url, quote=True) + '">查看并审批（无需登录）</a></p><p>打开邮件或链接不会直接批准。请在页面确认批准或填写退回原因。</p><p>本机演示链接：仅工作台所在电脑可访问。有效期7天，请勿转发。</p></body></html>', subtype="html")
    msg.add_attachment(summary, maintype="text", subtype="plain", filename="approval-summary.txt")
    for doc in selected:
        main, sub = doc["mime"].split(";", 1)[0].split("/", 1)
        msg.add_attachment(doc["data"], maintype=main, subtype=sub, filename=doc["name"])
    snapshot = {"kind": "approval", "version": item["version"], "item": item,
                "target": "财务审核" if item["stage"] == 0 else "老板审批",
                "documents": [{k: d[k] for k in ["id", "source", "name", "category"]} for d in selected],
                "generated_attachments": ["approval-summary.txt"], "email_approval_id": request_id}
    db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?,?)", (mid, item["order_id"], item["id"], recipient, subject, body, json.dumps(snapshot, ensure_ascii=False), msg.as_bytes(), actor, now()))
    if request_id:
        db.execute("UPDATE email_approvals SET status='superseded' WHERE item_id=? AND status='pending'", (item["id"],))
        db.execute("INSERT INTO email_approvals(id,token_hash,item_id,message_id,recipient,version,stage,expires,summary,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (request_id, hashlib.sha256(token.encode()).hexdigest(), item["id"], mid, recipient, item["version"], 2, expiry, summary_body, now()))
    event(db, item["order_id"], item["id"], actor, "审批邮件待发送", f"{snapshot['target']} · 收件人：{recipient}；附件 {len(selected)+1} 个；尚未发送。", snapshot)
    return mid


def email_approval(db, payload, decide=False):
    token = payload.get("token")
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{40,100}", token):
        raise ValueError("审批链接无效，请联系提交人重新发送。")
    row = db.execute("SELECT * FROM email_approvals WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    if not row:
        raise ValueError("审批链接无效，请联系提交人重新发送。")
    request = dict(row)
    item = item_for(db, request["item_id"])
    actionable = request["status"] == "pending" and datetime.fromisoformat(request["expires"]) > datetime.now().astimezone() and request["version"] == item["version"] and request["stage"] == item["stage"] and not approval_locked(db, item)
    if decide:
        if not actionable:
            raise ValueError("此审批链接已处理、已过期或资料已变更，不能再次审批。")
        decision, note = payload.get("decision"), clean(payload.get("note"))
        if decision not in ["approve", "return"] or payload.get("confirmed") is not True:
            raise ValueError("请明确选择批准或退回，并勾选确认。")
        if decision == "return" and not note:
            raise ValueError("退回时请填写原因。")
        mutate(db, "/api/transition", {"actor": "老板", "item_id": item["id"], "version": item["version"], "stage": item["stage"], "decision": "return" if decision == "return" else "next", "note": "邮件链接审批，指定收件人：" + request["recipient"] + ("；" + note if note else "")})
        db.execute("UPDATE email_approvals SET status=?,decided=?,decision_note=? WHERE id=? AND status='pending'", ("approved" if decision == "approve" else "returned", now(), note, request["id"]))
        event(db, item["order_id"], item["id"], "邮件审批链接", "邮件审批结果已回写", f"指定收件人：{request['recipient']}；{'批准' if decision == 'approve' else '退回'}；{note}", {"request_id": request["id"], "channel": "email-link", "intended_recipient": request["recipient"], "version": request["version"], "decision": decision, "identity_basis": "持有指定收件人的审批链接，未独立验证邮箱身份"})
        return {"message": "审批结果已记录，产品信息已锁定。" if decision == "approve" else "已退回补充，原因已记录。", "completed": True}
    message = db.execute("SELECT snapshot FROM messages WHERE id=?", (request["message_id"],)).fetchone()
    snapshot = json.loads(message[0])
    display_status = {"approved": "已批准", "returned": "已退回", "superseded": "已被新申请替代"}.get(request["status"], "等待审批" if actionable else "已过期、资料已变更或此节点已处理")
    return {"summary": request["summary"], "recipient": request["recipient"], "version": request["version"], "expires": request["expires"], "status": display_status, "actionable": actionable, "decided": request["decided"], "decision_note": request["decision_note"], "attachments": [{"name": d["name"], "category": d["category"]} for d in snapshot["documents"]]}


def state(db):
    orders = [dict(r) for r in db.execute("SELECT * FROM orders ORDER BY created DESC, invoice")]
    for order in orders:
        details = db.execute("SELECT metadata FROM order_details WHERE order_id=?", (order["id"],)).fetchone()
        order["source"] = json.loads(details[0]) if details else None
        order["source_documents"] = [dict(r) for r in db.execute("SELECT id,name,mime,category,sha256,actor,created,length(data) AS size FROM order_documents WHERE order_id=? ORDER BY created,id", (order["id"],))]
        order["items"] = []
        order["sales_locked"] = sales_locked(db, order["id"])
        for row in db.execute("SELECT * FROM items WHERE order_id=? ORDER BY line_no", (order["id"],)):
            item = item_for(db, row["id"])
            item["code"] = f'{order["invoice"]}-{item["line_no"]:02}'
            item["status"], item["owner"] = FLOWS[item["route"]][item["stage"]]
            item["flow"] = FLOWS[item["route"]]
            item["missing"] = missing(db, item)
            item["optional_missing"] = optional_missing(db, item)
            item["approval_locked"] = approval_locked(db, item)
            item["email_approvals"] = [dict(r) for r in db.execute("SELECT id,recipient,version,status,expires,decided,decision_note FROM email_approvals WHERE item_id=? ORDER BY created DESC", (item["id"],))]
            sales_line = db.execute("SELECT * FROM invoice_lines WHERE item_id=?", (item["id"],)).fetchone()
            item["invoice_line"] = dict(sales_line) if sales_line else None
            item["documents"] = [dict(r) for r in db.execute("SELECT id,name,mime,category,actor,created,length(data) AS size FROM documents WHERE item_id=? ORDER BY created DESC", (item["id"],))]
            item["messages"] = [dict(r) for r in db.execute("SELECT id,recipient,subject,body,snapshot,actor,created FROM messages WHERE item_id=? ORDER BY created DESC,rowid DESC", (item["id"],))]
            item["shipments"] = [dict(r) for r in db.execute("SELECT * FROM shipments WHERE item_id=? ORDER BY created DESC", (item["id"],))]
            order["items"].append(item)
        order["events"] = [dict(r) for r in db.execute("SELECT * FROM events WHERE order_id=? ORDER BY id DESC", (order["id"],))]
    return {"orders": orders, "roles": ROLES, "categories": CATEGORIES,
            "production_types": PRODUCTION_TYPES, "flows": FLOWS,
            "mode": "public-demo" if PUBLIC_DEMO else "local-prototype",
            "ephemeral_storage": EPHEMERAL_STORAGE,
            "test_reviewer_full_access": TEST_REVIEWER_FULL_ACCESS}


def check_role(actor, allowed):
    if TEST_REVIEWER_FULL_ACCESS and actor == "审核":
        return
    if actor not in allowed:
        raise ValueError("请切换到对应演示角色操作：" + "、".join(allowed))


def mutate(db, path, payload):
    actor = payload.get("actor")
    if actor not in ROLES:
        raise ValueError("请选择演示角色。")
    if path == "/api/import-preview":
        check_role(actor, ["销售", "财务"])
        from invoice_import import parse_export
        return parse_export(payload.get("file", {}))
    if path == "/api/import-invoice":
        from invoice_import import save_invoice
        import sys
        return save_invoice(db, payload, sys.modules[__name__])
    if path == "/api/orders":
        check_role(actor, ["销售"])
        invoice = clean(payload.get("invoice"), 100)
        customer = clean(payload.get("customer"), 200)
        sales = clean(payload.get("sales"), 100) or "待确认"
        due = valid_date(payload.get("due"), required=False)
        lines = payload.get("items", [])
        if not invoice or not customer or not sales or not isinstance(lines, list) or not 1 <= len(lines) <= 50:
            raise ValueError("请填写 Invoice、客户、销售及至少一个产品。")
        if db.execute("SELECT 1 FROM orders WHERE invoice=?", (invoice,)).fetchone():
            raise ValueError("这个 Invoice 已有档案，请打开原档案，勿重复建立。")
        oid = uid()
        db.execute("INSERT INTO orders VALUES(?,?,?,?,?,?)", (oid, invoice, customer, sales, due, now()))
        for n, line in enumerate(lines, 1):
            name, route = clean(line.get("name"), 200), UNCLASSIFIED
            if not name:
                raise ValueError("请填写产品名称。制作类型由销售后续补充。")
            qty = positive_int(line.get("qty"))
            iid = uid()
            db.execute("INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (iid, oid, n, name, qty, route, "", "", "", 0, "CAD", due, "", 0, 1, now()))
            event(db, oid, iid, actor, "新建产品", f"{name} · {qty} 个 · {route}", item_for(db, iid))
        event(db, oid, None, actor, "新建订单", f"Invoice {invoice} · {customer}")
        return {"order_id": oid}

    item = item_for(db, payload.get("item_id"))
    oid, iid = item["order_id"], item["id"]
    status, owner = FLOWS[item["route"]][item["stage"]]
    if path == "/api/approval-preview":
        check_role(actor, [owner])
        reissue = payload.get("reissue") is True and status == "老板审批" and not approval_locked(db, item)
        if (status not in ["待补资料", "财务审核"] and not reissue) or payload.get("version") != item["version"]:
            raise ValueError("当前资料或节点已变化，请刷新后重新提交审批。")
        subject, body, docs = approval_package(db, {**item, "stage": 1} if reissue else item, clean(payload.get("note")))
        return {"subject": subject, "body": body, "attachments": [{"key": d["key"], "name": d["name"], "size": len(d["data"]), "source": d["source"]} for d in docs]}
    if path == "/api/reissue-boss-approval":
        check_role(actor, ["审核", "老板"])
        if status != "老板审批" or approval_locked(db, item) or payload.get("version") != item["version"]:
            raise ValueError("请在当前版本的老板审批节点重新准备邮件。")
        mid = create_approval_draft(db, {**item, "stage": 1}, actor, payload, clean(payload.get("note")))
        return {"approval_message_id": mid, "message": "已重新准备老板审批邮件，旧链接已失效，尚未发送。"}
    if path == "/api/production-type":
        check_role(actor, ["销售"])
        if approval_locked(db, item):
            raise ValueError("老板已批准，制作类型和制作备注已锁定，不能修改。")
        if payload.get("version") != item["version"]:
            raise ValueError("资料已变化，请刷新后再补充制作类型。")
        route = payload.get("route")
        if route not in PRODUCTION_TYPES:
            raise ValueError("请选择制作类型：国内定制、本地直发或本地加工。")
        old_sales = db.execute("SELECT sales FROM orders WHERE id=?", (oid,)).fetchone()[0]
        sales = clean(payload.get("sales", old_sales), 100)
        if not sales or sales == "待确认":
            raise ValueError("请填写销售负责人姓名。")
        if sales != old_sales and sales_locked(db, oid):
            raise ValueError("此订单已有产品获老板批准，订单销售负责人已锁定，不能修改。")
        allowed = [UNCLASSIFIED, "待补资料", "财务审核", "老板审批", "库存预留"]
        executed = any(json.loads(r[0]).get("kind") != "approval" for r in db.execute("SELECT snapshot FROM messages WHERE item_id=?", (iid,))) or db.execute("SELECT 1 FROM shipments WHERE item_id=?", (iid,)).fetchone()
        if status not in allowed or executed:
            raise ValueError("此产品已进入执行，不能直接改制作类型；请先核实已有操作。")
        note = clean(payload.get("note"))
        production_notes = clean(payload.get("production_notes", item["production_notes"]))
        changing = item["route"] != UNCLASSIFIED and item["route"] != route
        if changing and not note:
            raise ValueError("更改已选制作类型时，请说明原因。")
        old_sales = db.execute("SELECT sales FROM orders WHERE id=?", (oid,)).fetchone()[0]
        if item["route"] == route and old_sales == sales and production_notes == item["production_notes"]:
            return {"message": "制作类型、制作备注及销售负责人没有变化。"}
        db.execute("UPDATE orders SET sales=? WHERE id=?", (sales, oid))
        if old_sales != sales:
            event(db, oid, None, actor, "登记销售负责人", f"{old_sales} → {sales}", {"before": old_sales, "after": sales})
        route_changed = item["route"] != route
        notes_changed = item["production_notes"] != production_notes
        if notes_changed:
            db.execute("INSERT INTO production_details(item_id,notes) VALUES(?,?) ON CONFLICT(item_id) DO UPDATE SET notes=excluded.notes", (iid, production_notes))
        if route_changed or notes_changed:
            db.execute("UPDATE items SET route=?,stage=?,version=version+1,updated=? WHERE id=?", (route, 0 if route_changed else item["stage"], now(), iid))
        if route_changed:
            event(db, oid, iid, actor, "更改制作类型" if changing else "确认制作类型",
                  f"{sales}：{item['route']} → {route}；进入{FLOWS[route][0][0]}。" + note,
                  {"before": item, "after": item_for(db, iid), "sales": sales, "reason": note})
        if notes_changed:
            event(db, oid, iid, actor, "更新制作备注", f"{sales}：{item['production_notes'] or '（空）'} → {production_notes or '（空）'}",
                  {"before": item["production_notes"], "after": production_notes, "item": item_for(db, iid)})
        return {"message": "销售已确认制作类型，已交接对应流程。" if route_changed else "销售负责人及制作备注已保存，当前节点保持不变。"}
    if path == "/api/item":
        check_role(actor, ["销售", "跟单"])
        if payload.get("version") != item["version"]:
            raise ValueError("资料已被修改，请刷新后再保存。")
        fields = ["name", "qty", "spec", "supplier", "recipient", "unit_cost", "currency", "due", "notes"]
        values = {k: clean(payload.get(k, item[k])) for k in fields}
        values["qty"] = positive_int(payload.get("qty", item["qty"]))
        values["due"] = valid_date(payload.get("due", item["due"]), required=False)
        try:
            values["unit_cost"] = float(payload.get("unit_cost", item["unit_cost"]))
            if not 0 <= values["unit_cost"] <= 1e9:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError("单价必须是有效的非负金额。")
        if not values["name"] or values["currency"] not in ["CAD", "USD", "CNY"]:
            raise ValueError("请填写产品名称并选择币种。")
        if values["recipient"] and not re.fullmatch(r"[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+", values["recipient"]):
            raise ValueError("请填写一个有效收件邮箱。")
        shipped = db.execute("SELECT COALESCE(SUM(qty),0) FROM shipments WHERE item_id=?", (iid,)).fetchone()[0]
        if values["qty"] < shipped:
            raise ValueError("订购数量不能小于已经登记的装运数量。")
        changes = {k: {"before": item[k], "after": values[k]} for k in fields if item[k] != values[k]}
        if not changes:
            return {"message": "资料没有变化。"}
        if status == "已完成":
            raise ValueError("已完成产品不能在此修改，请保留结案记录并另行处理变更。")
        critical = set(changes) - {"notes"}
        locked = approval_locked(db, item)
        if locked and critical:
            raise ValueError("老板已批准，产品名称、数量、交货要求、规格、供应商、邮箱、单价及币种已锁定，不能修改；可补充执行备注。")
        if critical and item["route"] != "本地直发" and item["stage"] >= 1:
            values["stage"] = 0
        db.execute("UPDATE items SET " + ",".join(f"{k}=?" for k in values) + (",updated=? WHERE id=?" if locked else ",version=version+1,updated=? WHERE id=?"), [*values.values(), now(), iid])
        detail = "；".join(f"{k}: {v['before']} → {v['after']}" for k, v in changes.items())
        if "stage" in values:
            detail += "；关键资料变更，已退回待补资料，需重新审核及批准。"
        event(db, oid, iid, actor, "修改资料", detail, {"changes": changes, "item": item_for(db, iid)})
        return {"message": "已保存修改和历史。"}

    if path == "/api/document":
        check_role(actor, ["销售", "跟单", "财务", "仓库", "物流"])
        if status == "已完成":
            raise ValueError("已完成产品的资料已冻结。")
        name = Path(clean(payload.get("name"), 200).replace("\\", "/")).name
        category = payload.get("category")
        if category in APPROVAL_CATEGORIES and approval_locked(db, item):
            raise ValueError("老板已批准，图稿/规格、报价及加工说明已锁定，不能追加变更；可上传工厂确认、付款或运输等执行凭证。")
        if not name or category not in CATEGORIES:
            raise ValueError("请选择文件及资料类别。")
        try:
            raw = base64.b64decode(payload.get("data", ""), validate=True)
        except Exception:
            raise ValueError("文件数据无效。")
        if not 0 < len(raw) <= 10 * 1024 * 1024:
            raise ValueError("单个附件须为 1 字节至 10MB。")
        did = uid()
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        db.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?)", (did, oid, iid, name, mime, category, raw, actor, now()))
        # New commercial/spec evidence changes the approval basis, so invalidate approval.
        reset = category in ["图稿/规格", "工厂报价", "加工说明"] and item["route"] != "本地直发" and item["stage"] >= 1
        if reset:
            db.execute("UPDATE items SET stage=0,version=version+1,updated=? WHERE id=?", (now(), iid))
        event(db, oid, iid, actor, "新增附件", f"{category} · {name}" + ("；审批依据变化，需重新提交审核。" if reset else ""), {"document_id": did, "category": category, "name": name})
        return {"message": "附件已归档。" + ("审批依据已变更，请重新提交审核。" if reset else "")}

    if path == "/api/comment":
        note = clean(payload.get("note"))
        if not note:
            raise ValueError("请填写备注或待补问题。")
        event(db, oid, iid, actor, "沟通备注", note)
        return {"message": "备注已记录。"}

    if path == "/api/transition":
        if status == "已完成":
            raise ValueError("此产品已完成，不能继续推进节点。")
        if item["route"] == UNCLASSIFIED:
            raise ValueError("请先由销售补充制作类型，之后才能推进节点。")
        check_role(actor, [owner] if owner else [])
        if payload.get("version") != item["version"] or payload.get("stage") != item["stage"]:
            raise ValueError("资料已变化，请刷新后审核。")
        note = clean(payload.get("note"))
        if payload.get("decision") == "return":
            if status not in ["财务审核", "老板审批"] or not note:
                raise ValueError("退回时请填写具体原因。")
            next_stage, action = 0, "退回补充"
        else:
            if status in ["待补资料", "财务审核", "老板审批"]:
                gaps = missing(db, item)
                if gaps:
                    raise ValueError("请先补齐：" + "、".join(gaps))
                if status == "待补资料" and optional_missing(db, item) and payload.get("confirm_optional_missing") is not True:
                    return {"confirmation_required": True, "optional_missing": optional_missing(db, item)}
            if status == "待下单":
                drafts = db.execute("SELECT snapshot FROM messages WHERE item_id=?", (iid,)).fetchall()
                if not any(json.loads(d[0])["version"] == item["version"] and json.loads(d[0]).get("kind") != "approval" for d in drafts):
                    raise ValueError("请先生成并归档当前版本的下单邮件，再手动发送。")
            cats = {r[0] for r in db.execute("SELECT category FROM documents WHERE item_id=?", (iid,))}
            if status == "等工厂确认" and "工厂确认" not in cats:
                raise ValueError("请上传工厂确认邮件或文件，类别选择“工厂确认”。")
            if status == "待发货" and "出库凭证" not in cats:
                raise ValueError("请先上传出库凭证。")
            if status == "待海运" and not db.execute("SELECT 1 FROM shipments WHERE item_id=?", (iid,)).fetchone():
                raise ValueError("请先登记至少一个海运批次。")
            if status == "海运中":
                arrived = db.execute("SELECT COALESCE(SUM(qty),0) FROM shipments WHERE item_id=? AND status='已到货'", (iid,)).fetchone()[0]
                if arrived != item["qty"]:
                    raise ValueError(f"已到货 {arrived}/{item['qty']}，全部数量到货后才能完成。")
            if status in ["待下单", "库存预留", "待送加工", "加工中"] and not note:
                raise ValueError("请填写操作说明，例如实际发送时间、库存预留位置或加工验收结果。")
            next_stage = item["stage"] + 1
            action = {"财务审核": "审核通过", "老板审批": "老板批准", "待补资料": "提交审核", "待下单": "人工确认邮件已发送"}.get(status, "完成节点")
        snap = {"item": item, "documents": [dict(r) for r in db.execute("SELECT id,name,category FROM documents WHERE item_id=?", (iid,))]}
        if status == "待补资料" and payload.get("decision") != "return" and optional_missing(db, item):
            snap["optional_attachments_confirmation"] = {"missing": optional_missing(db, item), "confirmed_by": actor}
            note += ("；" if note else "") + "已知悉可选附件未附：" + "、".join(optional_missing(db, item)) + "；确认继续提交。"
        next_status = FLOWS[item["route"]][next_stage][0]
        approval_mid = None
        if payload.get("decision") != "return" and status in ["待补资料", "财务审核"]:
            approval_mid = create_approval_draft(db, item, actor, payload, note)
            snap["approval_email"] = clean(payload.get("approval_email"), 250)
            snap["approval_message_id"] = approval_mid
        event(db, oid, iid, actor, action, f"V{item['version']} · {status} → {next_status}" + ("；" + note if note else ""), snap)
        db.execute("UPDATE items SET stage=?,updated=? WHERE id=?", (next_stage, now(), iid))
        return {"message": "已提交审批，审批邮件及附件已准备，等待手动发送。" if approval_mid else "已记录操作并交接下一位负责人。", "approval_message_id": approval_mid}

    if path == "/api/message":
        if item["route"] == UNCLASSIFIED:
            raise ValueError("请先由销售补充制作类型，再生成业务邮件。")
        check_role(actor, ["销售", "跟单", "物流"])
        if item["route"] != "本地直发" and item["stage"] < 3:
            raise ValueError("下单邮件需在老板批准后生成；请先完成资料审核和审批。")
        if status == "已完成":
            raise ValueError("此产品已完成。")
        if payload.get("version") != item["version"]:
            raise ValueError("资料已变化，请关闭并重新生成邮件草稿。")
        recipient, subject, body = clean(payload.get("recipient"), 250), clean(payload.get("subject"), 500), clean(payload.get("body"), 20000)
        if not re.fullmatch(r"[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+", recipient) or not subject or not body or "\n" in subject or "\r" in subject:
            raise ValueError("请填写有效收件邮箱、主题和正文。")
        ids = payload.get("document_ids", [])
        if not isinstance(ids, list) or len(ids) > 30:
            raise ValueError("附件选择无效。")
        docs = []
        for did in dict.fromkeys(ids):
            row = db.execute("SELECT * FROM documents WHERE id=? AND item_id=?", (did, iid)).fetchone()
            if not row:
                raise ValueError("附件不属于该产品或已失效。")
            docs.append(dict(row))
        if sum(len(d["data"]) for d in docs) > 20 * 1024 * 1024:
            raise ValueError("邮件附件总量不能超过20MB。")
        mid = uid()
        msg = EmailMessage(policy=policy.SMTP)
        msg["To"], msg["Subject"] = recipient, subject
        msg["X-Unsent"] = "1"
        msg["X-Order-Item"] = iid
        msg.set_content(body)
        for d in docs:
            main, sub = d["mime"].split(";", 1)[0].split("/", 1)
            msg.add_attachment(d["data"], maintype=main, subtype=sub, filename=d["name"])
        snap = {"kind": "business", "version": item["version"], "item": item, "documents": [{k: d[k] for k in ["id", "name", "category"]} for d in docs]}
        db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?,?)", (mid, oid, iid, recipient, subject, body, json.dumps(snap, ensure_ascii=False), msg.as_bytes(), actor, now()))
        event(db, oid, iid, actor, "邮件草稿归档（未发送）", f"收件人：{recipient}；主题：{subject}；附件 {len(docs)} 个", snap)
        return {"message_id": mid, "message": "草稿已归档，可下载 .eml 后手动发送。"}

    if path == "/api/shipment":
        check_role(actor, ["物流"])
        if item["route"] != "国内定制" or status not in ["待海运", "海运中"]:
            raise ValueError("请在待海运或海运中节点登记批次。")
        qty = positive_int(payload.get("qty"))
        total = db.execute("SELECT COALESCE(SUM(qty),0) FROM shipments WHERE item_id=?", (iid,)).fetchone()[0]
        if total + qty > item["qty"]:
            raise ValueError(f"超过订单数量：尚可登记 {item['qty'] - total} 个。")
        vessel, voyage, bl = [clean(payload.get(k), 150) for k in ["vessel", "voyage", "bl"]]
        etd, eta = valid_date(payload.get("etd")), valid_date(payload.get("eta"))
        if not vessel or not voyage or not bl or eta < etd:
            raise ValueError("请填写船名、航次、提单号，预计到港日不能早于开船日。")
        sid = uid()
        db.execute("INSERT INTO shipments VALUES(?,?,?,?,?,?,?,?,?,?,?)", (sid, oid, iid, qty, vessel, voyage, bl, etd, eta, "海运中", now()))
        event(db, oid, iid, actor, "登记海运批次", f"{qty} 个 · {vessel}/{voyage} · 提单 {bl}", payload)
        return {"message": "海运批次已登记。"}

    if path == "/api/arrive":
        check_role(actor, ["物流"])
        if status not in ["待海运", "海运中"]:
            raise ValueError("当前节点不允许确认到货。")
        shipment = db.execute("SELECT * FROM shipments WHERE id=? AND item_id=?", (payload.get("shipment_id"), iid)).fetchone()
        if not shipment or shipment["status"] != "海运中":
            raise ValueError("批次不存在或已经确认到货。")
        db.execute("UPDATE shipments SET status='已到货' WHERE id=?", (shipment["id"],))
        event(db, oid, iid, actor, "确认批次到货", f"提单 {shipment['bl']} · {shipment['qty']} 个", dict(shipment))
        return {"message": "已确认该批次到货。"}
    raise ValueError("不支持的操作。")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def respond(self, code, content, mime="application/json; charset=utf-8", filename=None):
        if not isinstance(content, bytes):
            content = json.dumps(content, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if PUBLIC_DEMO:
            self.send_header("X-Robots-Tag", "noindex, nofollow, noarchive")
        if filename:
            from urllib.parse import quote
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(filename))
        self.end_headers()
        self.wfile.write(content)

    def local_request(self):
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        origins = {"http://" + h for h in allowed}
        if PUBLIC_DEMO:
            public = urlparse(APPROVAL_BASE_URL)
            allowed.add(public.netloc)
            origins.add(APPROVAL_BASE_URL)
        if self.headers.get("Host") not in allowed:
            return False
        origin = self.headers.get("Origin")
        return not origin or origin in origins

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/healthz":
            return self.respond(200, {"status": "ok"})
        if not self.local_request():
            return self.respond(403, {"error": "仅允许本机工作台访问。"})
        if path == "/robots.txt":
            return self.respond(200, b"User-agent: *\nDisallow: /\n", "text/plain; charset=utf-8")
        with connect() as db:
            if path == "/api/state":
                return self.respond(200, state(db))
            if path.startswith("/api/document/"):
                row = db.execute("SELECT * FROM documents WHERE id=?", (path.rsplit("/", 1)[-1],)).fetchone()
                if row:
                    return self.respond(200, row["data"], row["mime"], row["name"])
            elif path.startswith("/api/order-document/") or path.startswith("/api/order-image/"):
                row = db.execute("SELECT * FROM order_documents WHERE id=?", (path.rsplit("/", 1)[-1],)).fetchone()
                if row:
                    if path.startswith("/api/order-image/"):
                        if row["mime"] not in ["image/png", "image/jpeg", "image/webp"]:
                            return self.respond(400, {"error": "此文件不支持图片预览。"})
                        return self.respond(200, row["data"], row["mime"])
                    return self.respond(200, row["data"], row["mime"], row["name"])
            elif path.startswith("/api/message/"):
                row = db.execute("SELECT * FROM messages WHERE id=?", (path.rsplit("/", 1)[-1],)).fetchone()
                if row:
                    return self.respond(200, row["eml"], "message/rfc822", "order-draft.eml")
            elif path == "/api/backup":
                output = io.BytesIO()
                with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr("orders.json", json.dumps(state(db), ensure_ascii=False, indent=2))
                    for row in db.execute("SELECT id,name,data FROM documents"):
                        archive.writestr(f"attachments/{row['id']}/{row['name']}", row["data"])
                    for row in db.execute("SELECT id,eml FROM messages"):
                        archive.writestr(f"emails/{row['id']}.eml", row["eml"])
                    for row in db.execute("SELECT id,name,data FROM order_documents"):
                        archive.writestr(f"order-sources/{row['id']}/{row['name']}", row["data"])
                return self.respond(200, output.getvalue(), "application/zip", "order-workbench-export.zip")
        assets = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/style.css": "style.css", "/manual.html": "manual.html", "/manual.js": "manual.js", "/approval.html": "approval.html", "/approval.js": "approval.js"}
        if path in assets:
            file = ROOT / assets[path]
            mime = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}[file.suffix]
            return self.respond(200, file.read_bytes(), mime + "; charset=utf-8")
        return self.respond(404, {"error": "记录或页面不存在。"})

    def do_POST(self):
        if not self.local_request() or not self.headers.get("Content-Type", "").startswith("application/json"):
            return self.respond(403, {"error": "请求来源或格式无效。"})
        try:
            size = int(self.headers.get("Content-Length", 0))
            if size <= 0 or size > 30 * 1024 * 1024:
                raise ValueError("请求太大或没有内容。")
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError("请求格式无效。")
            with connect() as db:
                db.execute("BEGIN IMMEDIATE")
                path = urlparse(self.path).path
                if path in ["/api/email-approval/view", "/api/email-approval/decide"]:
                    result = email_approval(db, payload, decide=path.endswith("/decide"))
                else:
                    result = mutate(db, path, payload)
            return self.respond(200, result)
        except (ValueError, TypeError, sqlite3.IntegrityError) as exc:
            return self.respond(400, {"error": str(exc)})
        except Exception:
            import traceback
            traceback.print_exc()
            return self.respond(500, {"error": "操作失败，未保存本次修改。请检查本地服务日志。"})


def configure_runtime(port):
    """Public, unauthenticated testing is explicit; local startup stays loopback-only."""
    global PUBLIC_DEMO, EPHEMERAL_STORAGE, DB_PATH, APPROVAL_BASE_URL
    PUBLIC_DEMO = os.environ.get("WORKBENCH_PUBLIC_DEMO") == "1"
    EPHEMERAL_STORAGE = PUBLIC_DEMO and os.environ.get("WORKBENCH_EPHEMERAL_STORAGE", "1") == "1"
    APPROVAL_BASE_URL = f"http://127.0.0.1:{port}"
    if PUBLIC_DEMO:
        raw = (os.environ.get("WORKBENCH_PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL", "")).rstrip("/")
        public = urlparse(raw)
        if (public.scheme != "https" or not public.hostname or public.username or public.password
                or public.path or public.query or public.fragment or public.port not in (None, 443)):
            raise ValueError("公开测试须设置有效的 HTTPS WORKBENCH_PUBLIC_URL 或 RENDER_EXTERNAL_URL。")
        APPROVAL_BASE_URL = raw
        folder = Path(os.environ.get("WORKBENCH_DATA_DIR", str(ROOT / ".render-demo-data"))).resolve()
        if folder == (ROOT / "data").resolve():
            raise ValueError("公开测试必须使用独立数据目录，不能使用本机订单目录。")
        DB_PATH = folder / "workbench.sqlite3"
    else:
        DB_PATH = ROOT / "data" / "workbench.sqlite3"
    return "0.0.0.0" if PUBLIC_DEMO else "127.0.0.1"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8766")))
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args()
    host = configure_runtime(args.port)
    init_db()
    server = ThreadingHTTPServer((host, args.port), Handler)
    print(f"Order workbench: {APPROVAL_BASE_URL}", flush=True)
    if args.open_browser:
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
