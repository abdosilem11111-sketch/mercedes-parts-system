# -*- coding: utf-8 -*-
"""
نظام إدارة مخازن ومبيعات قطع غيار مرسيدس - الإصدار الاحترافي
------------------------------------------------------------
التشغيل محلياً:
    pip install streamlit pandas
    streamlit run mercedes_parts_app.py

النشر على Streamlit Cloud:
    1) ارفع هذا الملف + ملف requirements.txt (يحتوي سطرين: streamlit و pandas) على GitHub
    2) (اختياري) من Settings > Secrets ضع:   APP_PASSWORD = "كلمة_المرور_الأولى"
       أو متغير بيئة MERCEDES_APP_PASSWORD. الافتراضي عند أول تشغيل: admin123
       (غيّرها فوراً من صفحة الإعدادات).
ملاحظة: ملفات Streamlit Cloud مؤقتة، لذا خُذ نسخة احتياطية دورياً من صفحة الإعدادات.
"""
import os, json, sqlite3, random, html, hmac, hashlib, secrets, time, datetime, urllib.parse
from pathlib import Path
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

DB = str(Path(__file__).with_name("mercedes_parts.db"))
BRANCHES = ["الفرع الرئيسي", "فرع الإسكندرية", "فرع الجيزة", "فرع طنطا"]
BCODE = {"الفرع الرئيسي": "HQ", "فرع الإسكندرية": "ALX", "فرع الجيزة": "GZ", "فرع طنطا": "TNT"}
ORIGINS = ["أصلي ألماني Original Germany", "بديل ألماني German Aftermarket", "تايواني Taiwan", "صيني China"]
SEARCH_COLS = ["part_number", "name", "category", "model", "brand", "quality_origin", "location", "barcode"]
LETTER = {"تيل فرامل": "A", "فرامل": "A", "فلاتر": "B", "طرمبات": "C", "كهرباء": "D", "عفشة": "E",
          "محرك": "F", "زيوت": "G"}
AR = {"id": "م", "part_number": "رقم OEM", "name": "اسم القطعة", "category": "الفئة", "model": "الموديل",
      "brand": "الماركة", "quality_origin": "المنشأ/الجودة", "quantity": "الكمية", "cost_price": "سعر التكلفة",
      "selling_price": "سعر البيع", "branch": "الفرع", "location": "مكان التخزين", "barcode": "الباركود"}
PERIODS = ["كل الفترة", "اليوم", "آخر 7 أيام", "آخر 30 يوم"]
SCOPES = ["كل الأصناف", "فئة", "ماركة", "منشأ/جودة", "موديل", "رقم OEM"]
OFFER_TYPES = ["نسبة %", "مبلغ ثابت للقطعة"]
SCAN_LABEL = "📷 امسح الباركود هنا ثم Enter"

# ============================================================== قاعدة البيانات
def conn():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def qdf(sql, p=()):
    c = conn()
    try:
        return pd.read_sql_query(sql, c, params=list(p))
    finally:
        c.close()

def run(sql, p=()):
    c = conn()
    try:
        c.execute(sql, p)
        c.commit()
    finally:
        c.close()

def get_setting(k, d=""):
    r = qdf("SELECT value FROM settings WHERE key=?", (k,))
    return r.iloc[0, 0] if not r.empty else d

def set_setting(k, v):
    run("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))

def low_limit():
    try:
        return max(1, int(get_setting("low_limit", "10")))
    except ValueError:
        return 10

# --- كلمة المرور
def hash_pw(pw, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt_hex), 150000).hex()

def set_password(pw, default=False):
    salt = secrets.token_hex(16)
    set_setting("pw_salt", salt)
    set_setting("pw_hash", hash_pw(pw, salt))
    set_setting("pw_default", "1" if default else "0")

def check_password(pw):
    salt, h = get_setting("pw_salt"), get_setting("pw_hash")
    return bool(salt and h) and hmac.compare_digest(hash_pw(pw, salt), h)

def initial_password():
    p = os.environ.get("MERCEDES_APP_PASSWORD")
    if p:
        return p, False
    try:
        return str(st.secrets["APP_PASSWORD"]), False
    except Exception:
        return "admin123", True

# --- البيانات التجريبية: 15 نوع × 5 موديلات × 4 جودات = 300 صنف
PART_TYPES = [
    ("تيل فرامل أمامي Front Brake Pads", "تيل فرامل", "420", 3800, "Bosch"),
    ("تيل فرامل خلفي Rear Brake Pads", "تيل فرامل", "423", 3200, "Bosch"),
    ("هوب فرامل أمامي Front Brake Disc", "فرامل", "421", 5200, "Febi"),
    ("فلتر زيت Oil Filter", "فلاتر", "180", 650, "Bosch"),
    ("فلتر هواء Air Filter", "فلاتر", "094", 900, "Bosch"),
    ("فلتر مكيف Cabin Filter", "فلاتر", "830", 700, "Bosch"),
    ("طرمبة بنزين Fuel Pump", "طرمبات", "470", 6500, "Bosch"),
    ("طرمبة مياه Water Pump", "طرمبات", "200", 4800, "Febi"),
    ("طقم شمعات اشتعال Spark Plugs Set", "كهرباء", "159", 2400, "Bosch"),
    ("مساعد أمامي Front Shock Absorber", "عفشة", "320", 7800, "Febi"),
    ("مقص أمامي Front Control Arm", "عفشة", "330", 4200, "Febi"),
    ("كرسي موتور Engine Mount", "محرك", "240", 2900, "Febi"),
    ("ثرموستات Thermostat", "محرك", "203", 1700, "Febi"),
    ("زيت محرك 5W-30 (4 لتر) Engine Oil", "زيوت", "989", 2300, "Febi"),
    ("بوبينة اشتعال Ignition Coil", "كهرباء", "150", 1800, "Bosch"),
]
MODELS = [("C-Class W204", "204", 0.90), ("C-Class W205", "205", 1.00), ("E-Class W212", "212", 1.05),
          ("E-Class W213", "213", 1.20), ("GLC X253", "253", 1.25)]

def seed(c):
    rng = random.Random(2024)
    rows = []
    for t, (tname, cat, grp, cost, de) in enumerate(PART_TYPES):
        for m, (model, chs, mm) in enumerate(MODELS):
            branch = BRANCHES[(t * len(MODELS) + m) % 4]
            oem = f"A{chs}{grp}{rng.choice(['00','01','02','03','04'])}{rng.choice(['00','10','20','28','31','32','37'])}"
            shelf = rng.randint(1, 20)
            variants = [("Mercedes-Benz", ORIGINS[0], "", 1.00, 1.30), (de, ORIGINS[1], "-" + de[:3].upper(), 0.68, 1.35),
                        ("TW-Auto", ORIGINS[2], "-TW", 0.42, 1.45), ("CN-Auto", ORIGINS[3], "-CN", 0.27, 1.55)]
            for vi, (brand, origin, suf, vm, margin) in enumerate(variants):
                cp = round(cost * mm * vm / 5) * 5
                sp = round(cp * margin / 5) * 5
                qty = rng.randint(0, 9) if rng.random() < 0.15 else rng.randint(10, 80)
                loc = f"{LETTER.get(cat, 'H')}-{shelf:02d}-{vi + 1}"
                rows.append((oem + suf, tname, cat, model, brand, origin, qty, cp, sp, branch, loc))
    c.executemany("INSERT INTO inventory(part_number,name,category,model,brand,quality_origin,quantity,cost_price,"
                  "selling_price,branch,location) VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)

def ensure_col(c, table, col, ddl):
    cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})")]
    if col not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        return True
    return False

def init_db():
    c = conn()
    c.execute("""CREATE TABLE IF NOT EXISTS inventory(
        id INTEGER PRIMARY KEY AUTOINCREMENT, part_number TEXT UNIQUE NOT NULL, name TEXT, category TEXT, model TEXT,
        brand TEXT, quality_origin TEXT, quantity INTEGER DEFAULT 0, cost_price REAL, selling_price REAL,
        branch TEXT, location TEXT DEFAULT '', barcode TEXT DEFAULT '')""")
    c.execute("""CREATE TABLE IF NOT EXISTS invoices(
        id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_no TEXT, date TEXT, customer TEXT, branch TEXT,
        inventory_id INTEGER, part_number TEXT, name TEXT, model TEXT, brand TEXT, quality_origin TEXT,
        qty INTEGER, unit_price REAL, total REAL, returned_qty INTEGER DEFAULT 0, status TEXT DEFAULT 'مكتملة',
        unit_cost REAL DEFAULT 0, customer_phone TEXT DEFAULT '', list_price REAL DEFAULT 0, discount_note TEXT DEFAULT '')""")
    c.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)")
    c.execute("""CREATE TABLE IF NOT EXISTS offers(
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, type TEXT, value REAL, scope TEXT, scope_value TEXT DEFAULT '',
        branch TEXT DEFAULT 'الكل', min_qty INTEGER DEFAULT 1, start_date TEXT DEFAULT '', end_date TEXT DEFAULT '',
        active INTEGER DEFAULT 1)""")
    c.execute("""CREATE TABLE IF NOT EXISTS transfers(
        id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, part_number TEXT, name TEXT, brand TEXT,
        quality_origin TEXT, from_branch TEXT, to_branch TEXT, qty INTEGER)""")
    # ترقية قواعد البيانات القديمة
    ensure_col(c, "inventory", "location", "TEXT DEFAULT ''")
    new_cost = ensure_col(c, "invoices", "unit_cost", "REAL DEFAULT 0")
    ensure_col(c, "invoices", "customer_phone", "TEXT DEFAULT ''")
    ensure_col(c, "invoices", "list_price", "REAL DEFAULT 0")
    ensure_col(c, "invoices", "discount_note", "TEXT DEFAULT ''")
    ensure_col(c, "inventory", "barcode", "TEXT DEFAULT ''")
    c.execute("CREATE INDEX IF NOT EXISTS idx_inv_barcode ON inventory(barcode)")
    c.execute("UPDATE invoices SET list_price=unit_price WHERE list_price IS NULL OR list_price=0")
    if new_cost:
        c.execute("UPDATE invoices SET unit_cost=COALESCE((SELECT cost_price FROM inventory "
                  "WHERE inventory.id=invoices.inventory_id),0)")
    if c.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 0:
        seed(c)
    for r in c.execute("SELECT id,category FROM inventory WHERE location IS NULL OR location=''").fetchall():
        c.execute("UPDATE inventory SET location=? WHERE id=?",
                  (f"{LETTER.get(r['category'], 'H')}-{r['id'] % 20 + 1:02d}-{r['id'] % 4 + 1}", r["id"]))
    for r in c.execute("SELECT id FROM inventory WHERE barcode IS NULL OR barcode=''").fetchall():
        c.execute("UPDATE inventory SET barcode=? WHERE id=?", (internal_barcode(r["id"]), r["id"]))
    for k, v in {"store_name": "قطع غيار مرسيدس", "store_phone": "", "store_address": "", "low_limit": "10",
                 "max_discount": "30"}.items():
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
    if not c.execute("SELECT 1 FROM settings WHERE key='pw_hash'").fetchone():
        pw, is_default = initial_password()
        salt = secrets.token_hex(16)
        for k, v in {"pw_salt": salt, "pw_hash": hash_pw(pw, salt), "pw_default": "1" if is_default else "0"}.items():
            c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (k, v))
    c.commit()
    c.close()

# ============================================================== البحث والبيانات
def search_inv(text="", branch=None, brand=None, origin=None):
    sql, p = "SELECT * FROM inventory WHERE 1=1", []
    for tok in (text or "").split():
        sql += " AND (" + " OR ".join(f"{c} LIKE ?" for c in SEARCH_COLS) + ")"
        p += [f"%{tok}%"] * len(SEARCH_COLS)
    if branch and branch != "الكل":
        sql += " AND branch=?"; p.append(branch)
    if brand and brand != "الكل":
        sql += " AND brand=?"; p.append(brand)
    if origin and origin != "الكل":
        sql += " AND quality_origin=?"; p.append(origin)
    return qdf(sql + " ORDER BY name, model, selling_price DESC", p)

def show(df):
    return df.rename(columns=AR)

def period_clause(period):
    today = datetime.date.today()
    start = {"اليوم": today, "آخر 7 أيام": today - datetime.timedelta(days=6),
             "آخر 30 يوم": today - datetime.timedelta(days=29)}.get(period)
    return (" AND date>=?", [start.isoformat()]) if start else ("", [])

def branch_clause(branch):
    return ("", []) if branch in (None, "الكل", "كل الفروع") else (" AND branch=?", [branch])

def dashboard_data(period):
    pc, pp = period_clause(period)
    low = low_limit()
    inv = qdf("""SELECT branch, COUNT(*) items, SUM(quantity) pieces, SUM(quantity*selling_price) val_sell,
        SUM(quantity*cost_price) val_cost, SUM(CASE WHEN quantity<? THEN 1 ELSE 0 END) low,
        SUM(CASE WHEN quantity=0 THEN 1 ELSE 0 END) zero FROM inventory GROUP BY branch""", (low,))
    inv = inv.set_index("branch").reindex(BRANCHES).fillna(0).astype(float)
    sal = qdf(f"""SELECT branch, SUM(qty*unit_price) gross, SUM(returned_qty*unit_price) ret,
        SUM((qty-returned_qty)*unit_price) net, SUM((qty-returned_qty)*(unit_price-unit_cost)) profit,
        SUM(qty*(list_price-unit_price)) disc, COUNT(DISTINCT invoice_no) n FROM invoices WHERE 1=1{pc} GROUP BY branch""", pp)
    sal = sal.set_index("branch").reindex(BRANCHES).fillna(0).astype(float)
    daily = qdf(f"SELECT substr(date,1,10) d, SUM((qty-returned_qty)*unit_price) s FROM invoices WHERE 1=1{pc} "
                f"GROUP BY d ORDER BY d", pp)
    top = qdf(f"""SELECT name, model, SUM(qty-returned_qty) pieces, SUM((qty-returned_qty)*unit_price) net
        FROM invoices WHERE 1=1{pc} GROUP BY name, model HAVING pieces>0 ORDER BY pieces DESC LIMIT 8""", pp)
    lows = qdf("SELECT * FROM inventory WHERE quantity<? ORDER BY quantity, branch LIMIT 15", (low,))
    return inv, sal, daily, top, lows

# ============================================================== الباركود والعروض
EAN_L = ["0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011"]
EAN_PAR = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG", "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"]

def ean_check(d12):
    return str((10 - sum(int(ch) * (3 if i % 2 else 1) for i, ch in enumerate(d12)) % 10) % 10)

def internal_barcode(i):
    d = "20" + f"{int(i):010d}"
    return d + ean_check(d)

def valid_ean13(code):
    code = str(code or "")
    return len(code) == 13 and code.isdigit() and ean_check(code[:12]) == code[12]

def ean13_bits(code):
    par = EAN_PAR[int(code[0])]
    bits = "101"
    for i, ch in enumerate(code[1:7]):
        l = EAN_L[int(ch)]
        r = "".join("1" if b == "0" else "0" for b in l)
        bits += l if par[i] == "L" else r[::-1]
    bits += "01010"
    for ch in code[7:13]:
        bits += "".join("1" if b == "0" else "0" for b in EAN_L[int(ch)])
    return bits + "101"

def ean13_svg(code, mw=2, h=56):
    bits, qz = ean13_bits(code), 9
    W, H = (95 + 2 * qz) * mw, h + 16
    rects, i = "", 0
    while i < 95:
        if bits[i] == "1":
            j = i
            while j < 95 and bits[j] == "1":
                j += 1
            g = 6 if (i < 3 or 45 <= i < 50 or i >= 92) else 0
            rects += f'<rect x="{(qz + i) * mw}" y="0" width="{(j - i) * mw}" height="{h + g}"/>'
            i = j
        else:
            i += 1
    t = 'font-family="monospace" font-size="12" fill="#000"'
    txt = (f'<text x="{(qz - 4) * mw}" y="{H - 2}" text-anchor="middle" {t}>{code[0]}</text>'
           f'<text x="{(qz + 3) * mw}" y="{H - 2}" textLength="{42 * mw}" lengthAdjust="spacing" {t}>{code[1:7]}</text>'
           f'<text x="{(qz + 50) * mw}" y="{H - 2}" textLength="{42 * mw}" lengthAdjust="spacing" {t}>{code[7:]}</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">'
            f'<rect width="{W}" height="{H}" fill="#fff"/><g fill="#000">{rects}</g>{txt}</svg>')

def focus_script():
    lb = json.dumps(SCAN_LABEL)
    return ("<script>setTimeout(function(){try{var d=window.parent.document;var e=d.querySelector('input[aria-label=\"'+" + lb +
            "+'\"]');if(e){e.focus();}}catch(x){}},350);/*" + str(time.time()) + "*/</script>")

def max_discount():
    try:
        return float(get_setting("max_discount", "30"))
    except ValueError:
        return 30.0

def active_offers(branch):
    today = datetime.date.today().isoformat()
    return qdf("SELECT * FROM offers WHERE active=1 AND (start_date='' OR start_date<=?) AND (end_date='' OR end_date>=?) "
               "AND (branch='الكل' OR branch=?)", (today, today, branch))

def offer_matches(o, it):
    s, v = o["scope"], str(o["scope_value"] or "")
    if s == "كل الأصناف":
        return True
    if s == "فئة":
        return it["category"] == v
    if s == "ماركة":
        return it["brand"] == v
    if s == "منشأ/جودة":
        return it["origin"] == v
    if s == "موديل":
        return it["model"] == v
    if s == "رقم OEM":
        return bool(v) and str(it["part_number"]).upper().startswith(v.upper())
    return False

def best_offer(it, qty, offers, lp):
    """أفضل عرض مطبّق (بدون تجميع عروض): يرجع (العرض أو None, قيمة الخصم للقطعة)."""
    best, bd = None, 0.0
    for _, o in offers.iterrows():
        if qty < int(o["min_qty"] or 1) or not offer_matches(o, it):
            continue
        d = lp * float(o["value"]) / 100 if o["type"] == OFFER_TYPES[0] else float(o["value"])
        d = min(max(d, 0.0), lp)
        if d > bd:
            best, bd = o, d
    return best, bd

def line_price(it, offers):
    lp = it["list"]
    if it["manual"] > 0:
        d, note = lp * it["manual"] / 100, f"خصم يدوي {it['manual']:g}%"
    else:
        o, d = best_offer(it, it["qty"], offers, lp)
        note = f"عرض: {o['name']}" if o is not None else ""
    it["price"], it["note"] = round(lp - d, 4), note

def cart_add(cart, r, qty, manual, offers):
    for it in cart:
        if it["id"] == int(r["id"]):
            it["qty"] += qty
            if manual > 0:
                it["manual"] = manual
            line_price(it, offers)
            return
    it = dict(id=int(r["id"]), pn=r["part_number"], part_number=r["part_number"], name=r["name"], model=r["model"],
              brand=r["brand"], origin=r["quality_origin"], category=r["category"], list=float(r["selling_price"]),
              cost=float(r["cost_price"] or 0), qty=int(qty), manual=float(manual))
    line_price(it, offers)
    cart.append(it)

# ============================================================== الفواتير
INV_CSS = """<style>*{box-sizing:border-box}.inv{font-family:Tahoma,Arial,sans-serif;color:#111;background:#fff;padding:22px;
max-width:900px;margin:auto;border:1px solid #d5dbe3;border-radius:10px}.inv h2{margin:0;color:#0b1f33}
.inv .sub{color:#555;font-size:13px;margin:2px 0}.inv .meta{display:flex;flex-wrap:wrap;gap:18px;background:#f3f6fa;
padding:10px 14px;border-radius:8px;margin:14px 0;font-size:14px}.inv table{width:100%;border-collapse:collapse;font-size:13px}
.inv td,.inv th{border:1px solid #c9d1db;padding:6px;text-align:center}.inv th{background:#0b1f33;color:#fff}
.inv .tot{margin-top:12px;text-align:left;font-size:15px}.inv .tot b{font-size:19px;color:#0b1f33}
.inv .foot{text-align:center;color:#666;font-size:12px;margin-top:16px}
.inv .btn{padding:9px 22px;font-size:15px;background:#1e88e5;color:#fff;border:0;border-radius:8px;cursor:pointer;margin-top:12px}
@media print{.np{display:none!important}.inv{border:0}@page{size:A4;margin:12mm}}</style>"""

def invoice_html(no, df):
    h = df.iloc[0]
    store, phone, addr = get_setting("store_name"), get_setting("store_phone"), get_setting("store_address")
    rows, before, disc, ret = "", 0.0, 0.0, 0.0
    for i, (_, r) in enumerate(df.iterrows(), 1):
        lp = r["list_price"] if r["list_price"] else r["unit_price"]
        before += r["qty"] * lp
        disc += r["qty"] * (lp - r["unit_price"])
        ret += r["returned_qty"] * r["unit_price"]
        net = (r["qty"] - r["returned_qty"]) * r["unit_price"]
        rows += (f"<tr><td>{i}</td><td>{html.escape(str(r['part_number']))}</td><td>{html.escape(str(r['name']))}</td>"
                 f"<td>{html.escape(str(r['model']))}</td><td>{html.escape(str(r['brand']))}</td>"
                 f"<td>{html.escape(str(r['quality_origin']))}</td><td>{r['qty']}</td><td>{r['returned_qty']}</td>"
                 f"<td>{lp:,.2f}</td><td>{r['unit_price']:,.2f}</td><td>{net:,.2f}</td></tr>")
    after = before - disc
    contact = " | ".join(x for x in [html.escape(phone), html.escape(addr)] if x)
    cust_phone = f" &nbsp;|&nbsp; <span><b>الهاتف:</b> {html.escape(str(h['customer_phone']))}</span>" if h["customer_phone"] else ""
    notes = sorted({str(n) for n in df["discount_note"].fillna("") if n})
    notes_txt = html.escape(" | ".join(notes))
    notes_html = f'<div class="sub" style="margin-top:8px"><b>العروض/الخصومات المطبقة:</b> {notes_txt}</div>' if notes else ""
    return (INV_CSS + f"""<div class="inv" dir="rtl"><div style="text-align:center"><h2>🚗 {html.escape(store)}</h2>
<div class="sub">{contact}</div><div class="sub"><b>فاتورة بيع</b></div></div>
<div class="meta"><span><b>رقم الفاتورة:</b> {no}</span><span><b>التاريخ:</b> {h['date']}</span>
<span><b>الفرع:</b> {html.escape(str(h['branch']))}</span><span><b>العميل:</b> {html.escape(str(h['customer']))}</span>{cust_phone}</div>
<table><tr><th>#</th><th>رقم OEM</th><th>الصنف</th><th>الموديل</th><th>الماركة</th><th>المنشأ</th><th>الكمية</th>
<th>مرتجع</th><th>السعر</th><th>بعد الخصم</th><th>الإجمالي</th></tr>{rows}</table>{notes_html}
<div class="tot">الإجمالي قبل الخصم: {before:,.2f} &nbsp;|&nbsp; الخصومات: {disc:,.2f} &nbsp;|&nbsp; الإجمالي بعد الخصم: {after:,.2f} EGP<br>
المرتجعات: {ret:,.2f} &nbsp;|&nbsp; الصافي: <b>{after - ret:,.2f} EGP</b></div><div class="foot">شكراً لتعاملكم معنا — يرجى الاحتفاظ بالفاتورة</div>
<div style="text-align:center"><button class="btn np" onclick="window.print()">🖨️ طباعة الفاتورة</button></div></div>""")

def invoice_text(no, df):
    h = df.iloc[0]
    lines = [f"{get_setting('store_name')}", f"فاتورة رقم: {no}", f"التاريخ: {h['date']}", f"العميل: {h['customer']}", "------"]
    total, disc = 0.0, 0.0
    for _, r in df.iterrows():
        lp = r["list_price"] if r["list_price"] else r["unit_price"]
        net = (r["qty"] - r["returned_qty"]) * r["unit_price"]
        total += net
        disc += (r["qty"] - r["returned_qty"]) * (lp - r["unit_price"])
        lines.append(f"- {r['name']} | {r['model']} | {r['brand']} ({r['quality_origin']}) × {r['qty'] - r['returned_qty']} = {net:,.2f}")
    if disc > 0.005:
        lines.append(f"إجمالي الخصم: {disc:,.2f}")
    lines += ["------", f"الإجمالي: {total:,.2f} EGP", "شكراً لتعاملكم معنا"]
    return "\n".join(lines)

def wa_phone(p):
    d = "".join(ch for ch in str(p or "") if ch.isdigit())
    if d.startswith("00"):
        d = d[2:]
    if len(d) == 11 and d.startswith("0"):
        d = "20" + d[1:]
    return d

def invoice_lines(no):
    return qdf("SELECT * FROM invoices WHERE invoice_no=? ORDER BY id", (no,))

def show_invoice(no, key):
    df = invoice_lines(no)
    if df.empty:
        return
    frag = invoice_html(no, df)
    components.html(frag, height=430 + 38 * len(df), scrolling=True)
    full = (f'<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>{no}</title></head>'
            f"<body style='background:#f3f6fa;margin:0;padding:16px'>{frag}</body></html>")
    msg = invoice_text(no, df)
    wa = f"https://wa.me/{wa_phone(df.iloc[0]['customer_phone'])}?text={urllib.parse.quote(msg)}"
    mail = f"mailto:?subject={urllib.parse.quote('فاتورة ' + no)}&body={urllib.parse.quote(msg)}"
    a, b, c, d = st.columns(4)
    a.download_button("⬇️ تحميل الفاتورة (HTML)", full, file_name=f"{no}.html", mime="text/html", key=f"dh_{key}_{no}")
    b.download_button("📄 تحميل نص الفاتورة", msg, file_name=f"{no}.txt", mime="text/plain", key=f"dt_{key}_{no}")
    c.markdown(f'<a class="linkbtn" href="{html.escape(wa)}" target="_blank">💬 مشاركة عبر واتساب</a>', unsafe_allow_html=True)
    d.markdown(f'<a class="linkbtn mail" href="{html.escape(mail)}" target="_blank">✉️ مشاركة بالبريد</a>', unsafe_allow_html=True)
    st.caption("للطباعة اضغط زر الطباعة داخل الفاتورة، ولحفظها PDF اختر (Save as PDF) من نافذة الطباعة. "
               "واتساب يفتح محادثة العميل مباشرة إذا أُدخل رقم هاتفه.")

def confirm_sale(branch, customer, phone, cart, dmode="بدون", dval=0.0):
    c = conn()
    try:
        need = {}
        for it in cart:
            need[it["id"]] = need.get(it["id"], 0) + it["qty"]
        costs = {}
        for iid, n in need.items():
            r = c.execute("SELECT quantity,name,brand,cost_price FROM inventory WHERE id=?", (iid,)).fetchone()
            if r is None or r["quantity"] < n:
                raise ValueError(f"الكمية غير كافية للصنف: {r['name'] if r else iid} ({r['brand'] if r else ''}) "
                                 f"- المتاح {r['quantity'] if r else 0}")
            costs[iid] = r["cost_price"] or 0
        sub = sum(it["qty"] * it["price"] for it in cart)
        dval = max(0.0, float(dval or 0))
        if dmode == "نسبة %":
            if dval > max_discount():
                raise ValueError(f"نسبة الخصم أكبر من الحد المسموح ({max_discount():g}%)")
            inv_disc = sub * dval / 100
        elif dmode == "مبلغ":
            inv_disc = dval
        else:
            inv_disc = 0.0
        inv_disc = min(inv_disc, sub)
        no = f"INV-{c.execute('SELECT COUNT(DISTINCT invoice_no) FROM invoices').fetchone()[0] + 1:06d}"
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        for it in cart:
            line_total = it["qty"] * it["price"]
            share = inv_disc * line_total / sub if sub > 0 else 0.0
            unit = (line_total - share) / it["qty"]
            note = " + ".join(x for x in [it.get("note", ""), "خصم فاتورة" if inv_disc > 0 else ""] if x)
            c.execute("UPDATE inventory SET quantity=quantity-? WHERE id=? AND quantity>=?", (it["qty"], it["id"], it["qty"]))
            c.execute("""INSERT INTO invoices(invoice_no,date,customer,branch,inventory_id,part_number,name,model,brand,
                quality_origin,qty,unit_price,total,returned_qty,status,unit_cost,customer_phone,list_price,discount_note)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0,'مكتملة',?,?,?,?)""",
                      (no, now, customer, branch, it["id"], it["pn"], it["name"], it["model"], it["brand"], it["origin"],
                       it["qty"], unit, line_total - share, costs[it["id"]], phone, it["list"], note))
        c.commit()
        return no
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

def do_return(items):
    c = conn()
    try:
        for lid, q in items:
            r = c.execute("SELECT * FROM invoices WHERE id=?", (lid,)).fetchone()
            if q <= 0 or q > r["qty"] - r["returned_qty"]:
                raise ValueError("كمية المرتجع غير صحيحة")
            newret = r["returned_qty"] + q
            c.execute("UPDATE invoices SET returned_qty=?, status=? WHERE id=?",
                      (newret, "مرتجعة" if newret == r["qty"] else "مرتجعة جزئياً", lid))
            c.execute("UPDATE inventory SET quantity=quantity+? WHERE id=?", (q, r["inventory_id"]))
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

# ============================================================== التصميم
CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700;800&display=swap');
.stApp{background:#f3f6fa;color:#1b2733;direction:rtl;font-family:'Cairo',sans-serif}
input,textarea,button,select{font-family:'Cairo',sans-serif!important}
.block-container{padding-top:1.4rem;max-width:1400px}
#MainMenu,footer{visibility:hidden}header[data-testid="stHeader"]{background:transparent}
.stApp h1,.stApp h2,.stApp h3,.stApp h4{color:#0b1f33;font-weight:800}
.stApp label p,.stApp .stMarkdown p{color:#1b2733}
.stTextInput input,.stNumberInput input,.stTextArea textarea{background:#fff!important;color:#1b2733!important;border-radius:10px}
[data-baseweb="select"]>div{background:#fff!important;color:#1b2733!important;border-radius:10px}
[data-testid="stSidebar"]{background:linear-gradient(180deg,#0b1f33 0%,#12385c 100%);direction:rtl}
[data-testid="stSidebar"] label p,[data-testid="stSidebar"] p,[data-testid="stSidebar"] span,
[data-testid="stSidebar"] .stMarkdown p,[data-testid="stSidebar"] .stCaption{color:#e8eef5!important}
[data-testid="stSidebar"] [role="radiogroup"]>label{background:rgba(255,255,255,.06);border-radius:10px;padding:8px 12px;
margin-bottom:6px;width:100%;transition:.15s}
[data-testid="stSidebar"] [role="radiogroup"]>label:hover{background:rgba(255,255,255,.16)}
[data-testid="stSidebar"] [role="radiogroup"]>label:has(input:checked){background:#1e88e5}
.brand{text-align:center;color:#fff;font-size:1.25rem;font-weight:800;padding:8px 0 14px;line-height:1.7}
.brand small{display:block;color:#9fb6cc;font-weight:400;font-size:.8rem}
.page-head{background:linear-gradient(120deg,#0b1f33,#1e6aa8);border-radius:16px;padding:18px 26px;margin-bottom:18px;
box-shadow:0 4px 16px rgba(11,31,51,.18)}
.page-head h2,.page-head p{color:#fff!important;margin:0}.page-head p{opacity:.8;font-size:.9rem;margin-top:4px}
.kpi{background:#fff;border-radius:14px;padding:14px 16px;box-shadow:0 2px 10px rgba(15,42,67,.08);
border-top:4px solid var(--c);margin-bottom:12px;height:112px}
.kpi .kt{font-size:.85rem;color:#5b6b7c}.kpi .kv{font-size:1.55rem;font-weight:800;color:#0b1f33;margin:2px 0}
.kpi .ks{font-size:.75rem;color:#8795a5}
.blue{--c:#1e88e5}.green{--c:#2e9e6b}.red{--c:#d64545}.amber{--c:#e69b12}.teal{--c:#0aa3a3}.slate{--c:#5b6b7c}
.bcard{background:#fff;border-radius:14px;padding:14px 16px;box-shadow:0 2px 10px rgba(15,42,67,.08);
border-right:5px solid #1e88e5;margin-bottom:12px;font-size:.88rem;line-height:1.9}
.bcard h4{margin:0 0 4px;font-size:1.05rem}.bcard b{color:#0b1f33}.bad{color:#d64545;font-weight:700}
.stButton>button,.stDownloadButton>button,[data-testid="stFormSubmitButton"]>button{border-radius:10px;font-weight:700;
border:1px solid #1e88e5;color:#1e88e5;background:#fff}
.stButton>button:hover,.stDownloadButton>button:hover{background:#1e88e5;color:#fff;border-color:#1e88e5}
.stButton>button[kind="primary"],[data-testid="stBaseButton-primary"],[data-testid="stFormSubmitButton"]>button[kind="primaryFormSubmit"]{
background:#1e88e5;color:#fff;border:0}
[data-testid="stSidebar"] .stButton>button{background:rgba(255,255,255,.1);color:#fff;border:1px solid rgba(255,255,255,.3);width:100%}
[data-testid="stDataFrame"],[data-testid="stDataEditor"]{direction:ltr;border-radius:12px;overflow:hidden}
.linkbtn{display:inline-block;padding:.5rem 1rem;border-radius:10px;background:#25d366;color:#fff!important;font-weight:700;
text-decoration:none;font-size:.9rem}.linkbtn.mail{background:#5b6b7c}
.login-card{background:#fff;border-radius:18px;padding:28px;box-shadow:0 8px 30px rgba(11,31,51,.15);text-align:center;margin-top:8vh}
.login-card h2{margin:6px 0}
</style>"""

def head(icon, title, sub=""):
    st.markdown(f'<div class="page-head"><h2>{icon} {title}</h2><p>{sub}</p></div>', unsafe_allow_html=True)

def kpi(title, value, sub="", tone="blue"):
    return f'<div class="kpi {tone}"><div class="kt">{title}</div><div class="kv">{value}</div><div class="ks">{sub}</div></div>'

def egp(x):
    return f"{x:,.0f} ج.م"

def csv_btn(df, label, name, key):
    st.download_button(label, df.to_csv(index=False).encode("utf-8-sig"), name, "text/csv", key=key)

# ============================================================== الصفحات
def page_dashboard():
    head("📈", "لوحة التحكم الرئيسية", "نظرة شاملة ومحدثة على كل الفروع")
    if get_setting("pw_default", "0") == "1":
        st.warning("⚠️ كلمة المرور الحالية هي الافتراضية. غيّرها الآن من صفحة الإعدادات لحماية بياناتك.")
    period = st.radio("الفترة الزمنية", PERIODS, horizontal=True, key="d_period")
    inv, sal, daily, top, lows = dashboard_data(period)
    t, s = inv.sum(), sal.sum()
    r1 = st.columns(4)
    r1[0].markdown(kpi("إجمالي المبيعات", egp(s["gross"]), f"{int(s['n'])} فاتورة", "blue"), unsafe_allow_html=True)
    r1[1].markdown(kpi("المرتجعات", egp(s["ret"]), "قيمة البضاعة المرتجعة", "red"), unsafe_allow_html=True)
    r1[2].markdown(kpi("صافي المبيعات", egp(s["net"]), "بعد خصم المرتجعات", "teal"), unsafe_allow_html=True)
    r1[3].markdown(kpi("صافي الأرباح", egp(s["profit"]), "المبيعات − التكلفة", "green"), unsafe_allow_html=True)
    r2 = st.columns(4)
    r2[0].markdown(kpi("قيمة المخزون (بسعر البيع)", egp(t["val_sell"]), f"{int(t['pieces']):,} قطعة", "blue"), unsafe_allow_html=True)
    r2[1].markdown(kpi("قيمة المخزون (بالتكلفة)", egp(t["val_cost"]), f"ربح متوقع {egp(t['val_sell'] - t['val_cost'])}", "slate"), unsafe_allow_html=True)
    r2[2].markdown(kpi("أصناف المخزون", f"{int(t['items']):,}", "في كل الفروع", "teal"), unsafe_allow_html=True)
    r2[3].markdown(kpi("تنبيهات النواقص", f"{int(t['low'])}", f"منها {int(t['zero'])} نفدت تماماً (الحد {low_limit()})", "amber"), unsafe_allow_html=True)
    today = datetime.date.today().isoformat()
    n_off = int(qdf("SELECT COUNT(*) c FROM offers WHERE active=1 AND (start_date='' OR start_date<=?) AND (end_date='' OR end_date>=?)",
                    (today, today)).iloc[0, 0])
    r3 = st.columns(4)
    r3[0].markdown(kpi("الخصومات الممنوحة", egp(s["disc"]), "عروض + خصومات يدوية + خصم الفواتير", "amber"), unsafe_allow_html=True)
    r3[1].markdown(kpi("المبيعات قبل الخصم", egp(s["gross"] + s["disc"]), "بأسعار القائمة", "slate"), unsafe_allow_html=True)
    r3[2].markdown(kpi("العروض الفعّالة", f"{n_off}", "تُطبَّق تلقائياً في POS", "teal"), unsafe_allow_html=True)
    r3[3].markdown(kpi("متوسط الفاتورة", egp(s["net"] / s["n"] if s["n"] else 0), "صافي بعد الخصم والمرتجعات", "blue"), unsafe_allow_html=True)
    st.subheader("أداء الفروع")
    cols = st.columns(4)
    for col, b in zip(cols, BRANCHES):
        col.markdown(f"""<div class="bcard"><h4>🏬 {b}</h4>
صافي المبيعات: <b>{egp(sal.loc[b, 'net'])}</b><br>صافي الربح: <b>{egp(sal.loc[b, 'profit'])}</b><br>
المرتجعات: <b>{egp(sal.loc[b, 'ret'])}</b><br>قيمة المخزون: <b>{egp(inv.loc[b, 'val_sell'])}</b><br>
نواقص: <span class="bad">{int(inv.loc[b, 'low'])}</span> صنف</div>""", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    c1.subheader("المبيعات والأرباح حسب الفرع")
    c1.bar_chart(pd.DataFrame({"صافي المبيعات": sal["net"], "صافي الربح": sal["profit"]}))
    c2.subheader("المبيعات اليومية")
    if daily.empty:
        c2.info("لا توجد مبيعات في هذه الفترة.")
    else:
        c2.line_chart(daily.set_index("d")["s"])
    c3, c4 = st.columns(2)
    c3.subheader("🏆 الأكثر مبيعاً")
    if top.empty:
        c3.info("لا توجد مبيعات بعد.")
    else:
        c3.dataframe(top.rename(columns={"name": "الصنف", "model": "الموديل", "pieces": "القطع", "net": "صافي المبيعات"}), hide_index=True)
    c4.subheader("⚠️ أهم النواقص")
    if lows.empty:
        c4.success("لا توجد نواقص 👌")
    else:
        c4.dataframe(show(lows)[["الفرع", "اسم القطعة", "الموديل", "الماركة", "الكمية", "مكان التخزين"]], hide_index=True)

def page_search():
    head("🔍", "البحث الذكي الموحد", "ابحث برقم OEM أو الاسم أو الموديل أو الماركة أو المنشأ أو مكان التخزين")
    q = st.text_input("كلمات البحث", key="s_q", placeholder="مثال: تيل W205 bosch  |  A2054200  |  تايواني  |  A-07")
    br = st.selectbox("الفرع", ["الكل"] + BRANCHES, key="s_br")
    df = search_inv(q, br)
    st.caption(f"عدد النتائج: {len(df)}")
    st.dataframe(show(df).drop(columns=["م"]), hide_index=True)

def page_pos():
    head("🧾", "شاشة المبيعات (POS)", "ابحث أو امسح الباركود، واختر الماركة، وتُطبَّق العروض والخصومات تلقائياً")
    c1, c2, c3 = st.columns(3)
    branch = c1.selectbox("الفرع", BRANCHES, key="pos_branch")
    customer = c2.text_input("اسم العميل", key="pos_customer")
    phone = c3.text_input("رقم هاتف العميل (لمشاركة الفاتورة واتساب)", key="pos_phone")
    cart = st.session_state.setdefault("cart", [])
    if cart and st.session_state.get("cart_branch") != branch:
        cart.clear()
    offers, maxd = active_offers(branch), max_discount()
    if not offers.empty:
        st.info("🏷️ عروض فعّالة في هذا الفرع: " + " ، ".join(offers["name"].tolist()))
    # --- المسح بالباركود (قارئ الباركود يكتب الرقم ثم Enter)
    with st.form("scan_form", clear_on_submit=True):
        code = st.text_input(SCAN_LABEL, key="scan_code")
        scanned = st.form_submit_button("➕ إضافة بالباركود")
    components.html(focus_script(), height=0)
    if scanned and code.strip():
        code = code.strip()
        m = qdf("SELECT * FROM inventory WHERE branch=? AND (barcode=? OR UPPER(part_number)=UPPER(?))", (branch, code, code))
        if m.empty:
            o2 = qdf("SELECT branch,quantity FROM inventory WHERE barcode=? OR UPPER(part_number)=UPPER(?)", (code, code))
            if o2.empty:
                st.error(f"الباركود {code} غير مسجل في النظام.")
            else:
                st.warning("الصنف غير موجود في هذا الفرع، متوفر في: " + " ، ".join(f"{r['branch']} ({r['quantity']})" for _, r in o2.iterrows()))
        else:
            r = m.iloc[0]
            in_cart = sum(i["qty"] for i in cart if i["id"] == int(r["id"]))
            if r["quantity"] <= in_cart:
                st.error(f"نفدت الكمية المتاحة من {r['name']} ({r['brand']}).")
            else:
                cart_add(cart, r, 1, 0.0, offers)
                st.session_state["cart_branch"] = branch
                st.success(f"✔️ تمت إضافة: {r['name']} — {r['brand']} ({r['quality_origin']})")
    # --- البحث اليدوي
    text = st.text_input("🔍 ابحث عن القطعة (OEM / اسم / موديل / ماركة / منشأ / باركود)", key="pos_q")
    if text.strip():
        res = search_inv(text, branch)
        if res.empty:
            st.warning("لا توجد نتائج في هذا الفرع.")
        else:
            groups = res.groupby(["name", "model"], sort=False).size().reset_index()
            gmap = {f"{r['name']} | {r['model']}": (r["name"], r["model"]) for _, r in groups.iterrows()}
            nm, md = gmap[st.selectbox("اختر القطعة", list(gmap.keys()), key="pos_sel")]
            alts = qdf("SELECT * FROM inventory WHERE branch=? AND name=? AND model=? ORDER BY selling_price DESC", (branch, nm, md))
            q1, q2 = st.columns(2)
            qty = q1.number_input("الكمية", min_value=1, value=1, step=1, key="pos_qty")
            manual = q2.number_input(f"خصم يدوي على الصنف % (أقصى {maxd:g}%) — يحل محل العرض", min_value=0.0,
                                     max_value=float(maxd), value=0.0, step=1.0, key="pos_manual")
            st.subheader("البدائل والماركات المتاحة لنفس القطعة والموديل")
            rows = []
            for _, a in alts.iterrows():
                lp = float(a["selling_price"])
                o, d = best_offer(dict(part_number=a["part_number"], category=a["category"], brand=a["brand"],
                                       origin=a["quality_origin"], model=a["model"]), int(qty), offers, lp)
                rows.append({"رقم OEM": a["part_number"], "الماركة": a["brand"], "المنشأ/الجودة": a["quality_origin"],
                             "الباركود": a["barcode"], "سعر البيع": lp, "العرض": o["name"] if o is not None else "—",
                             "السعر بعد العرض": lp - d, "الكمية": a["quantity"], "مكان التخزين": a["location"]})
            st.dataframe(pd.DataFrame(rows), hide_index=True)
            opts = {f"{r['brand']} - {r['quality_origin']} | {r['selling_price']:,.0f} ج.م | متاح {r['quantity']}": r
                    for _, r in alts.iterrows()}
            r = opts[st.selectbox("اختر الماركة/المنشأ", list(opts.keys()), key="pos_alt")]
            if st.button("➕ إضافة للفاتورة", type="primary"):
                in_cart = sum(i["qty"] for i in cart if i["id"] == int(r["id"]))
                if qty + in_cart > r["quantity"]:
                    st.error(f"الكمية المطلوبة أكبر من المتاح ({r['quantity']}).")
                else:
                    cart_add(cart, r, int(qty), float(manual), offers)
                    st.session_state["cart_branch"] = branch
                    st.rerun()
            other = qdf("SELECT branch,brand,quality_origin,quantity,selling_price,location FROM inventory "
                        "WHERE name=? AND model=? AND branch<>? ORDER BY branch", (nm, md, branch))
            if not other.empty:
                with st.expander("توفر نفس القطعة في الفروع الأخرى"):
                    st.dataframe(show(other), hide_index=True)
    # --- الفاتورة
    st.subheader("🛒 بنود الفاتورة")
    if cart:
        for it in cart:
            line_price(it, offers)
        for i, it in enumerate(cart):
            a, b = st.columns([8, 1])
            note_txt = f" ({it['note']})" if it["note"] else ""
            a.write(f"{i + 1}. {it['name']} | {it['model']} | {it['brand']} ({it['origin']}) × {it['qty']} | "
                    f"{it['list']:,.2f} ← {it['price']:,.2f}{note_txt} = {it['qty'] * it['price']:,.2f} EGP")
            if b.button("🗑️", key=f"rm{i}"):
                cart.pop(i); st.rerun()
        sub = sum(i["qty"] * i["price"] for i in cart)
        before = sum(i["qty"] * i["list"] for i in cart)
        v = st.session_state.get("pos_v", 0)
        d1, d2 = st.columns(2)
        dmode = d1.radio("خصم إضافي على إجمالي الفاتورة", ["بدون", "نسبة %", "مبلغ"], horizontal=True, key=f"pos_dmode_{v}")
        dval = d2.number_input("قيمة الخصم", min_value=0.0, value=0.0, step=1.0, key=f"pos_dval_{v}", disabled=(dmode == "بدون"))
        dval = 0.0 if dmode == "بدون" else float(dval)
        over = dmode == "نسبة %" and dval > maxd
        if over:
            st.error(f"نسبة الخصم أكبر من الحد المسموح ({maxd:g}%). عدّلها أو غيّر الحد من الإعدادات.")
        inv_disc = min(sub * dval / 100 if dmode == "نسبة %" else dval, sub)
        if any(i["price"] < i["cost"] for i in cart) or sub - inv_disc < sum(i["qty"] * i["cost"] for i in cart):
            st.warning("⚠️ تنبيه: الفاتورة بعد الخصم أقل من تكلفة بعض الأصناف.")
        k = st.columns(4)
        k[0].markdown(kpi("قبل الخصم", egp(before), "بأسعار القائمة", "slate"), unsafe_allow_html=True)
        k[1].markdown(kpi("خصم الأصناف/العروض", egp(before - sub), "", "amber"), unsafe_allow_html=True)
        k[2].markdown(kpi("خصم الفاتورة", egp(inv_disc), "", "amber"), unsafe_allow_html=True)
        k[3].markdown(kpi("الإجمالي النهائي", egp(sub - inv_disc), "EGP", "green"), unsafe_allow_html=True)
        if st.button("✅ تأكيد البيع وإصدار الفاتورة", type="primary", key="pos_confirm", disabled=over):
            try:
                st.session_state["last_invoice"] = confirm_sale(branch, customer.strip() or "عميل نقدي", phone.strip(), cart, dmode, dval)
                st.session_state["pos_v"] = v + 1
                cart.clear()
                st.rerun()
            except ValueError as e:
                st.error(str(e))
    else:
        st.info("الفاتورة فارغة.")
    no = st.session_state.get("last_invoice")
    if no:
        st.success(f"تم إصدار الفاتورة {no} وخصم الكميات من المخزن.")
        show_invoice(no, "pos")
        if st.button("🆕 فاتورة جديدة"):
            st.session_state.pop("last_invoice", None); st.rerun()

def page_inventory():
    head("📦", "إدارة وتعديل المخزون", "تعديل الكميات والأسعار وأماكن التخزين وإضافة أصناف جديدة")
    brands = qdf("SELECT DISTINCT brand FROM inventory ORDER BY brand")["brand"].tolist()
    c1, c2, c3 = st.columns(3)
    br = c1.selectbox("الفرع", ["الكل"] + BRANCHES, key="inv_br")
    bd = c2.selectbox("الماركة", ["الكل"] + brands, key="inv_bd")
    og = c3.selectbox("المنشأ/الجودة", ["الكل"] + ORIGINS, key="inv_og")
    q = st.text_input("🔍 بحث شامل موحد", key="inv_q")
    orig = show(search_inv(q, br, bd, og)).reset_index(drop=True)
    orig[AR["location"]] = orig[AR["location"]].fillna("")
    st.caption(f"عدد الأصناف: {len(orig)} — عدّل (الكمية / التكلفة / سعر البيع / مكان التخزين) ثم اضغط حفظ.")
    num_cols = [AR["quantity"], AR["cost_price"], AR["selling_price"]]
    ver = st.session_state.get("inv_v", 0)
    ed = st.data_editor(orig, hide_index=True, key=f"ed_{br}_{bd}_{og}_{q}_{ver}",
                        disabled=[c for c in orig.columns if c not in num_cols + [AR["location"]]],
                        column_config={AR["quantity"]: st.column_config.NumberColumn(min_value=0, step=1),
                                       AR["cost_price"]: st.column_config.NumberColumn(min_value=0),
                                       AR["selling_price"]: st.column_config.NumberColumn(min_value=0)})
    a, b = st.columns([1, 4])
    if a.button("💾 حفظ التعديلات", type="primary"):
        n = 0
        for i in ed.index:
            o, e = orig.loc[i], ed.loc[i]
            if any(float(o[c]) != float(e[c]) for c in num_cols) or str(o[AR["location"]]) != str(e[AR["location"]] or ""):
                run("UPDATE inventory SET quantity=?, cost_price=?, selling_price=?, location=? WHERE id=?",
                    (int(e[AR["quantity"]]), float(e[AR["cost_price"]]), float(e[AR["selling_price"]]),
                     str(e[AR["location"]] or "").strip(), int(o[AR["id"]])))
                n += 1
        if n:
            st.session_state["inv_v"] = ver + 1
            st.success(f"تم تحديث {n} صنف."); st.rerun()
        else:
            st.info("لا توجد تعديلات.")
    with b:
        csv_btn(orig, "⬇️ تصدير الجدول (CSV)", "inventory.csv", "inv_csv")
    st.divider()
    st.subheader("➕ إضافة قطعة جديدة")
    with st.form("add_part", clear_on_submit=True):
        a, b, c = st.columns(3)
        pn, name, cat = a.text_input("رقم OEM (فريد)"), b.text_input("اسم القطعة"), c.text_input("الفئة")
        model, brand, origin = a.text_input("الموديل"), b.text_input("الماركة"), c.selectbox("المنشأ/الجودة", ORIGINS)
        origin2, branch, loc = a.text_input("منشأ آخر (اختياري)"), b.selectbox("الفرع", BRANCHES), c.text_input("مكان التخزين (رف/صف)")
        qty = a.number_input("الكمية", min_value=0, value=0, step=1)
        cp = b.number_input("سعر التكلفة", min_value=0.0, value=0.0, step=10.0)
        sp = c.number_input("سعر البيع", min_value=0.0, value=0.0, step=10.0)
        barcode = a.text_input("الباركود (اتركه فارغاً للتوليد التلقائي)")
        if st.form_submit_button("حفظ القطعة", type="primary"):
            pn, bc_in = pn.strip(), barcode.strip()
            if not pn or not name.strip() or not brand.strip():
                st.error("رقم OEM والاسم والماركة مطلوبة.")
            elif not qdf("SELECT id FROM inventory WHERE UPPER(part_number)=UPPER(?)", (pn,)).empty:
                st.error("رقم الـ OEM موجود بالفعل!")
            elif bc_in and not qdf("SELECT id FROM inventory WHERE barcode=?", (bc_in,)).empty:
                st.error("هذا الباركود مستخدم لصنف آخر!")
            else:
                c = conn()
                try:
                    cur = c.execute("""INSERT INTO inventory(part_number,name,category,model,brand,quality_origin,quantity,
                        cost_price,selling_price,branch,location,barcode) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                                    (pn, name.strip(), cat.strip(), model.strip(), brand.strip(), origin2.strip() or origin,
                                     int(qty), cp, sp, branch, loc.strip(), bc_in))
                    if not bc_in:
                        c.execute("UPDATE inventory SET barcode=? WHERE id=?", (internal_barcode(cur.lastrowid), cur.lastrowid))
                    c.commit()
                finally:
                    c.close()
                st.success("تمت إضافة القطعة."); st.rerun()

def page_transfer():
    head("🔄", "تحويل المخزون بين الفروع", "نقل كمية من صنف محدد بماركته من فرع إلى آخر")
    c1, c2 = st.columns(2)
    src = c1.selectbox("من فرع", BRANCHES, key="tr_src")
    dst = c2.selectbox("إلى فرع", [b for b in BRANCHES if b != src], key="tr_dst")
    q = st.text_input("🔍 ابحث عن الصنف", key="tr_q")
    df = search_inv(q, src)
    df = df[df["quantity"] > 0]
    if df.empty:
        st.info("لا توجد أصناف متاحة للتحويل بهذا البحث.")
    else:
        opts = {f"{r['part_number']} | {r['name']} | {r['model']} | {r['brand']} ({r['quality_origin']}) | متاح {r['quantity']}": r
                for _, r in df.iterrows()}
        r = opts[st.selectbox("الصنف", list(opts.keys()), key="tr_item")]
        a, b = st.columns(2)
        qty = a.number_input("الكمية المنقولة", min_value=1, max_value=int(r["quantity"]), value=1, step=1, key="tr_qty")
        newloc = b.text_input("مكان التخزين في الفرع المستلم (إذا كان الصنف جديداً عليه)", key="tr_loc")
        if st.button("نقل الكمية", type="primary"):
            c = conn()
            try:
                if c.execute("SELECT quantity FROM inventory WHERE id=?", (int(r["id"]),)).fetchone()["quantity"] < qty:
                    st.error("الرصيد غير كافٍ.")
                else:
                    base = r["part_number"].split("/")[0]
                    d = c.execute("SELECT id FROM inventory WHERE branch=? AND (part_number=? OR part_number LIKE ?)",
                                  (dst, base, base + "/%")).fetchone()
                    c.execute("UPDATE inventory SET quantity=quantity-? WHERE id=?", (int(qty), int(r["id"])))
                    if d:
                        c.execute("UPDATE inventory SET quantity=quantity+? WHERE id=?", (int(qty), d["id"]))
                    else:
                        c.execute("""INSERT INTO inventory(part_number,name,category,model,brand,quality_origin,quantity,
                            cost_price,selling_price,branch,location,barcode) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                                  (f"{base}/{BCODE[dst]}", r["name"], r["category"], r["model"], r["brand"], r["quality_origin"],
                                   int(qty), r["cost_price"], r["selling_price"], dst, newloc.strip() or "غير محدد", r["barcode"]))
                    c.execute("INSERT INTO transfers(date,part_number,name,brand,quality_origin,from_branch,to_branch,qty) "
                              "VALUES (?,?,?,?,?,?,?,?)", (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), base, r["name"],
                                                           r["brand"], r["quality_origin"], src, dst, int(qty)))
                    c.commit()
                    st.success(f"تم نقل {qty} قطعة من {src} إلى {dst} وتحديث الرصيدين.")
            except Exception as e:
                c.rollback(); st.error(f"فشل التحويل: {e}")
            finally:
                c.close()
    st.subheader("سجل آخر التحويلات")
    log = qdf("SELECT date,part_number,name,brand,quality_origin,from_branch,to_branch,qty FROM transfers ORDER BY id DESC LIMIT 30")
    st.dataframe(log.rename(columns={"date": "التاريخ", "part_number": "رقم OEM", "name": "الصنف", "brand": "الماركة",
                                     "quality_origin": "المنشأ", "from_branch": "من", "to_branch": "إلى", "qty": "الكمية"}), hide_index=True)

def page_returns():
    head("↩️", "مرتجعات المبيعات", "إرجاع صنف أو فاتورة كاملة مع إعادة الكميات للمخزن")
    raw = st.text_input("رقم الفاتورة (مثال: INV-000001 أو 1)", key="ret_no").strip().upper()
    if not raw:
        return
    no = f"INV-{int(raw):06d}" if raw.isdigit() else raw
    df = invoice_lines(no)
    if df.empty:
        st.error("الفاتورة غير موجودة."); return
    st.write(f"العميل: **{df.iloc[0]['customer']}** | الفرع: **{df.iloc[0]['branch']}** | التاريخ: {df.iloc[0]['date']}")
    st.dataframe(df[["part_number", "name", "model", "brand", "quality_origin", "qty", "returned_qty", "unit_price", "status"]].rename(
        columns={**AR, "qty": "الكمية المباعة", "returned_qty": "المرتجع", "unit_price": "سعر الوحدة", "status": "الحالة"}), hide_index=True)
    df["rem"] = df["qty"] - df["returned_qty"]
    avail = df[df["rem"] > 0]
    if avail.empty:
        st.info("تم إرجاع هذه الفاتورة بالكامل."); return
    mode = st.radio("نوع المرتجع", ["إرجاع الفاتورة بالكامل", "إرجاع صنف/كمية محددة"], key="ret_mode", horizontal=True)
    if mode.startswith("إرجاع الفاتورة"):
        if st.button("تنفيذ إرجاع كامل الفاتورة", type="primary"):
            do_return([(int(r["id"]), int(r["rem"])) for _, r in avail.iterrows()])
            st.success("تم إرجاع الفاتورة وإعادة الكميات للمخزن."); st.rerun()
    else:
        opts = {f"{r['name']} | {r['brand']} ({r['quality_origin']}) | المتبقي للإرجاع {r['rem']}": r for _, r in avail.iterrows()}
        r = opts[st.selectbox("الصنف", list(opts.keys()), key="ret_item")]
        q = st.number_input("كمية المرتجع", min_value=1, max_value=int(r["rem"]), value=1, step=1, key="ret_qty")
        if st.button("تنفيذ المرتجع", type="primary"):
            do_return([(int(r["id"]), int(q))])
            st.success("تم تنفيذ المرتجع وإعادة الكمية للمخزن."); st.rerun()

def page_history():
    head("🗂️", "سجل الفواتير والمبيعات", "بحث وعرض وطباعة ومشاركة الفواتير السابقة")
    c1, c2 = st.columns(2)
    q = c1.text_input("بحث برقم الفاتورة أو اسم العميل أو هاتفه", key="h_q").strip()
    br = c2.selectbox("الفرع", ["الكل"] + BRANCHES, key="h_br")
    sql = """SELECT invoice_no, MIN(date) date, customer, customer_phone, branch, SUM(qty) qty, SUM(returned_qty) returned,
        SUM(qty*(list_price-unit_price)) discount, SUM((qty-returned_qty)*unit_price) net_total, CASE WHEN SUM(returned_qty)=0 THEN 'مكتملة'
        WHEN SUM(qty)=SUM(returned_qty) THEN 'مرتجعة' ELSE 'مرتجعة جزئياً' END status FROM invoices WHERE 1=1"""
    p = []
    if q:
        sql += " AND (invoice_no LIKE ? OR customer LIKE ? OR customer_phone LIKE ?)"; p += [f"%{q}%"] * 3
    bc, bp = branch_clause(br)
    df = qdf(sql + bc + " GROUP BY invoice_no ORDER BY invoice_no DESC", p + bp)
    ren = {"invoice_no": "رقم الفاتورة", "date": "التاريخ", "customer": "العميل", "customer_phone": "الهاتف", "branch": "الفرع",
           "qty": "عدد القطع", "returned": "المرتجع", "discount": "الخصم", "net_total": "الصافي EGP", "status": "الحالة"}
    st.dataframe(df.rename(columns=ren), hide_index=True)
    if not df.empty:
        csv_btn(df.rename(columns=ren), "⬇️ تصدير السجل (CSV)", "invoices.csv", "h_csv")
        no = st.selectbox("عرض / طباعة / مشاركة فاتورة", df["invoice_no"].tolist(), key="h_sel")
        show_invoice(no, "hist")

def page_reports():
    head("📊", "التقارير التفصيلية", "تحليلات المبيعات والمخزون مع إمكانية التصدير")
    c1, c2 = st.columns(2)
    br = c1.selectbox("الفرع", ["كل الفروع"] + BRANCHES, key="rp_br")
    period = c2.radio("الفترة", PERIODS, horizontal=True, key="rp_p")
    pc, pp = period_clause(period)
    bc, bp = branch_clause(br)
    t1, t2, t3, t4, t5 = st.tabs(["المبيعات حسب الماركة/المنشأ", "أفضل الأصناف مبيعاً", "حالة المخزون", "النواقص", "الخصومات والعروض"])
    with t1:
        bo = qdf(f"""SELECT brand, quality_origin, SUM(qty-returned_qty) pieces, SUM((qty-returned_qty)*unit_price) net,
            SUM((qty-returned_qty)*(unit_price-unit_cost)) profit FROM invoices WHERE 1=1{pc}{bc}
            GROUP BY brand, quality_origin ORDER BY net DESC""", pp + bp)
        if bo.empty:
            st.info("لا توجد مبيعات.")
        else:
            out = bo.rename(columns={"brand": "الماركة", "quality_origin": "المنشأ", "pieces": "القطع", "net": "صافي المبيعات", "profit": "الربح"})
            st.dataframe(out, hide_index=True)
            st.bar_chart(bo.assign(l=bo["brand"] + " - " + bo["quality_origin"]).set_index("l")[["net", "profit"]])
            csv_btn(out, "⬇️ تصدير (CSV)", "sales_by_brand.csv", "rp_c1")
    with t2:
        tp = qdf(f"""SELECT name, model, SUM(qty-returned_qty) pieces, SUM((qty-returned_qty)*unit_price) net FROM invoices
            WHERE 1=1{pc}{bc} GROUP BY name, model HAVING pieces>0 ORDER BY pieces DESC LIMIT 20""", pp + bp)
        out = tp.rename(columns={"name": "الصنف", "model": "الموديل", "pieces": "القطع", "net": "صافي المبيعات"})
        st.dataframe(out, hide_index=True)
        if not tp.empty:
            csv_btn(out, "⬇️ تصدير (CSV)", "top_items.csv", "rp_c2")
    with t3:
        bw, bwp = branch_clause(br)
        st_df = qdf(f"""SELECT branch, quality_origin, COUNT(*) items, SUM(quantity) pieces, SUM(quantity*selling_price) val
            FROM inventory WHERE 1=1{bw} GROUP BY branch, quality_origin ORDER BY branch""", bwp)
        out = st_df.rename(columns={"branch": "الفرع", "quality_origin": "المنشأ", "items": "الأصناف", "pieces": "القطع", "val": "القيمة (بيع)"})
        st.dataframe(out, hide_index=True)
        csv_btn(out, "⬇️ تصدير (CSV)", "stock_status.csv", "rp_c3")
    with t4:
        lim = st.number_input("حد النواقص (أقل من)", min_value=1, value=low_limit(), step=1, key="rp_lim")
        lw = qdf(f"SELECT * FROM inventory WHERE quantity<?{bc} ORDER BY quantity, branch", [int(lim)] + bp)
        out = show(lw).drop(columns=["م"])
        st.caption(f"عدد الأصناف الناقصة: {len(out)}")
        st.dataframe(out, hide_index=True)
        if not out.empty:
            csv_btn(out, "⬇️ تصدير قائمة النواقص (CSV)", "low_stock.csv", "rp_c4")
    with t5:
        bd = qdf(f"""SELECT branch, SUM(qty*list_price) gross_list, SUM(qty*(list_price-unit_price)) disc FROM invoices
            WHERE 1=1{pc}{bc} GROUP BY branch""", pp + bp)
        out = bd.rename(columns={"branch": "الفرع", "gross_list": "المبيعات قبل الخصم", "disc": "الخصومات الممنوحة"})
        st.dataframe(out, hide_index=True)
        st.subheader("الخصومات حسب العرض/النوع")
        nt = qdf(f"""SELECT discount_note, COUNT(*) lines, SUM(qty*(list_price-unit_price)) disc FROM invoices
            WHERE discount_note<>''{pc}{bc} GROUP BY discount_note ORDER BY disc DESC""", pp + bp)
        out2 = nt.rename(columns={"discount_note": "العرض / نوع الخصم", "lines": "عدد البنود", "disc": "قيمة الخصم"})
        st.dataframe(out2, hide_index=True)
        if not nt.empty:
            csv_btn(out2, "⬇️ تصدير (CSV)", "discounts.csv", "rp_c5")

def page_settings():
    head("⚙️", "الإعدادات", "بيانات المحل، حد النواقص، كلمة المرور، والنسخ الاحتياطي")
    st.subheader("بيانات المحل (تظهر في الفاتورة)")
    with st.form("store_form"):
        a, b = st.columns(2)
        name = a.text_input("اسم المحل", get_setting("store_name"))
        phone = b.text_input("هاتف المحل", get_setting("store_phone"))
        addr = a.text_input("العنوان", get_setting("store_address"))
        lim = b.number_input("حد تنبيه النواقص", min_value=1, value=low_limit(), step=1)
        mdisc = a.number_input("أقصى نسبة خصم مسموحة % (يدوي أو على الفاتورة)", min_value=0, max_value=100,
                               value=int(max_discount()), step=1)
        if st.form_submit_button("حفظ الإعدادات", type="primary"):
            for k, v in {"store_name": name.strip() or "قطع غيار مرسيدس", "store_phone": phone.strip(),
                         "store_address": addr.strip(), "low_limit": int(lim), "max_discount": int(mdisc)}.items():
                set_setting(k, v)
            st.success("تم حفظ الإعدادات."); st.rerun()
    st.subheader("🔐 تغيير كلمة المرور")
    with st.form("pw_form", clear_on_submit=True):
        old, new, new2 = st.text_input("الحالية", type="password"), st.text_input("الجديدة (6 أحرف على الأقل)", type="password"), \
            st.text_input("تأكيد الجديدة", type="password")
        if st.form_submit_button("تغيير كلمة المرور"):
            if not check_password(old):
                st.error("كلمة المرور الحالية غير صحيحة.")
            elif len(new) < 6 or new != new2:
                st.error("كلمة المرور الجديدة قصيرة أو غير متطابقة.")
            else:
                set_password(new); st.success("تم تغيير كلمة المرور.")
    st.subheader("💾 النسخ الاحتياطي والاستعادة")
    if Path(DB).exists():
        st.download_button("⬇️ تحميل نسخة احتياطية من قاعدة البيانات", Path(DB).read_bytes(),
                           file_name=f"mercedes_parts_backup_{datetime.date.today()}.db", mime="application/octet-stream")
    up = st.file_uploader("استعادة من نسخة احتياطية (.db)", type=["db", "sqlite"])
    if up is not None and st.checkbox("أؤكد أن بيانات النظام الحالية ستُستبدل بالكامل"):
        if st.button("استعادة النسخة"):
            tmp = DB + ".tmp"
            Path(tmp).write_bytes(up.getvalue())
            try:
                t = sqlite3.connect(tmp)
                names = {r[0] for r in t.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                t.close()
                if {"inventory", "invoices"} <= names:
                    os.replace(tmp, DB); init_db(); st.success("تمت الاستعادة بنجاح.")
                else:
                    os.remove(tmp); st.error("الملف ليس نسخة صالحة من النظام.")
            except sqlite3.DatabaseError:
                os.remove(tmp); st.error("الملف غير صالح.")

def page_offers():
    head("🏷️", "العروض والخصومات", "أنشئ عروضاً تُطبَّق تلقائياً في شاشة المبيعات حسب الفرع والفترة والكمية")
    st.caption(f"الحد الأقصى للخصم اليدوي/الفاتورة حالياً {max_discount():g}% (يُغيَّر من الإعدادات). "
               "عند تطابق أكثر من عرض يُطبَّق الأفضل للعميل فقط (بدون تجميع).")
    today = datetime.date.today().isoformat()
    df = qdf("SELECT * FROM offers ORDER BY active DESC, id DESC")
    if df.empty:
        st.info("لا توجد عروض بعد. أنشئ أول عرض من النموذج بالأسفل.")
    else:
        def status(r):
            if not r["active"]:
                return "⏸️ متوقف"
            if r["start_date"] and r["start_date"] > today:
                return "⏳ قادم"
            if r["end_date"] and r["end_date"] < today:
                return "⌛ منتهي"
            return "✅ فعّال"
        view = df.assign(status=df.apply(status, axis=1)).drop(columns=["active"])
        st.dataframe(view.rename(columns={"id": "م", "name": "اسم العرض", "type": "نوع الخصم", "value": "القيمة", "scope": "ينطبق على",
                                          "scope_value": "قيمة النطاق", "branch": "الفرع", "min_qty": "أقل كمية",
                                          "start_date": "من", "end_date": "إلى", "status": "الحالة"}), hide_index=True)
        opts = {f"#{r['id']} {r['name']}": r for _, r in df.iterrows()}
        sel = opts[st.selectbox("إدارة عرض", list(opts.keys()), key="of_manage")]
        a, b, _ = st.columns([1, 1, 3])
        if a.button("⏯️ تفعيل / إيقاف"):
            run("UPDATE offers SET active=? WHERE id=?", (0 if sel["active"] else 1, int(sel["id"]))); st.rerun()
        if b.button("🗑️ حذف العرض"):
            run("DELETE FROM offers WHERE id=?", (int(sel["id"]),)); st.rerun()
    st.divider()
    st.subheader("➕ عرض جديد")
    name = st.text_input("اسم العرض (مثال: خصم الصيف على التيل)", key="of_name")
    c1, c2, c3 = st.columns(3)
    typ = c1.selectbox("نوع الخصم", OFFER_TYPES, key="of_type")
    val = c2.number_input("قيمة الخصم", min_value=0.0, value=10.0, step=1.0, key="of_val")
    minq = c3.number_input("أقل كمية لتطبيق العرض (للعروض الكمية)", min_value=1, value=1, step=1, key="of_minq")
    s1, s2 = st.columns(2)
    scope = s1.selectbox("ينطبق على", SCOPES, key="of_scope")
    sval = ""
    if scope == "فئة":
        sval = s2.selectbox("الفئة", qdf("SELECT DISTINCT category v FROM inventory ORDER BY v")["v"].tolist(), key="of_sv1")
    elif scope == "ماركة":
        sval = s2.selectbox("الماركة", qdf("SELECT DISTINCT brand v FROM inventory ORDER BY v")["v"].tolist(), key="of_sv2")
    elif scope == "منشأ/جودة":
        sval = s2.selectbox("المنشأ/الجودة", ORIGINS, key="of_sv3")
    elif scope == "موديل":
        sval = s2.selectbox("الموديل", qdf("SELECT DISTINCT model v FROM inventory ORDER BY v")["v"].tolist(), key="of_sv4")
    elif scope == "رقم OEM":
        sval = s2.text_input("رقم OEM أو بدايته (مثال: A20542)", key="of_sv5").strip()
    d1, d2, d3, d4 = st.columns(4)
    obr = d1.selectbox("الفرع", ["الكل"] + BRANCHES, key="of_br")
    start = d2.date_input("بداية العرض", value=datetime.date.today(), key="of_start")
    no_end = d3.checkbox("بدون تاريخ انتهاء", value=False, key="of_noend")
    end = d4.date_input("نهاية العرض", value=datetime.date.today() + datetime.timedelta(days=7), key="of_end", disabled=no_end)
    if st.button("💾 حفظ العرض", type="primary", key="of_save"):
        if not name.strip():
            st.error("اسم العرض مطلوب.")
        elif val <= 0 or (typ == OFFER_TYPES[0] and val > 100):
            st.error("قيمة الخصم غير صحيحة (النسبة بين 0 و100).")
        elif scope != "كل الأصناف" and not sval:
            st.error("حدد قيمة النطاق.")
        elif not no_end and end < start:
            st.error("تاريخ النهاية قبل البداية.")
        else:
            run("""INSERT INTO offers(name,type,value,scope,scope_value,branch,min_qty,start_date,end_date,active)
                VALUES (?,?,?,?,?,?,?,?,?,1)""", (name.strip(), typ, float(val), scope, sval, obr, int(minq),
                                                  start.isoformat(), "" if no_end else end.isoformat()))
            st.success("تم حفظ العرض وسيُطبَّق تلقائياً في المبيعات."); st.rerun()

LABEL_CSS = """<style>.lbs{display:flex;flex-wrap:wrap;gap:3mm;direction:rtl;font-family:Tahoma,Arial,sans-serif}
.lb{width:60mm;border:1px dashed #999;padding:2mm;text-align:center;page-break-inside:avoid;background:#fff;color:#111}
.lb svg{max-width:100%;height:auto}.ln{font-size:11px;font-weight:700;line-height:1.25}.lm{font-size:10px;color:#444}
.lp{font-size:12px;font-weight:700}.lp span{font-size:10px;color:#555;margin-right:6px}
.btn{padding:8px 20px;font-size:15px;background:#1e88e5;color:#fff;border:0;border-radius:8px;cursor:pointer;margin:6px 0}
@media print{.np{display:none!important}@page{margin:6mm}}</style>"""

def labels_html(rows, copies, by_qty):
    cells, skipped = "", []
    for r in rows:
        code = str(r["barcode"] or "")
        if not valid_ean13(code):
            skipped.append(r["part_number"]); continue
        n = min(100, max(1, int(r["quantity"])) if by_qty else int(copies))
        cell = (f'<div class="lb"><div class="ln">{html.escape(str(r["name"])[:42])}</div>'
                f'<div class="lm">{html.escape(str(r["model"]))} | {html.escape(str(r["brand"]))}</div>{ean13_svg(code)}'
                f'<div class="lp">{r["selling_price"]:,.0f} ج.م<span>{html.escape(str(r["location"] or ""))}</span></div></div>')
        cells += cell * n
    page = (LABEL_CSS + '<button class="btn np" onclick="window.print()">🖨️ طباعة الملصقات</button>'
            f'<div class="lbs">{cells}</div>')
    return page, skipped

def page_barcode():
    head("🔖", "الباركود", "طباعة ملصقات الباركود وتعيين باركود مخصص — ويُمسح مباشرة في شاشة المبيعات والبحث")
    t1, t2 = st.tabs(["🖨️ طباعة الملصقات", "✏️ تعيين / تعديل باركود"])
    with t1:
        c1, c2 = st.columns(2)
        br = c1.selectbox("الفرع", ["الكل"] + BRANCHES, key="bc_br")
        q = c2.text_input("🔍 بحث عن الأصناف", key="bc_q")
        df = search_inv(q, br).head(300)
        opts = {f"{r['part_number']} | {r['name']} | {r['model']} | {r['brand']} | {r['branch']}": r for _, r in df.iterrows()}
        all_res = st.checkbox("اختيار كل نتائج البحث الحالية (حتى 60 صنف)", key="bc_all")
        picked = [] if all_res else st.multiselect("اختر الأصناف", list(opts.keys()), key="bc_pick")
        x1, x2 = st.columns(2)
        copies = x1.number_input("عدد الملصقات لكل صنف", min_value=1, max_value=100, value=1, step=1, key="bc_copies")
        by_qty = x2.checkbox("عدد الملصقات = الكمية الموجودة بالمخزن", key="bc_byqty")
        rows = list(opts.values())[:60] if all_res else [opts[k] for k in picked]
        if rows:
            page, skipped = labels_html(rows, copies, by_qty)
            if skipped:
                st.warning("لا يمكن رسم ملصق لهذه الأصناف لأن باركودها المخصص ليس EAN-13: " + " ، ".join(skipped[:8]))
            components.html(page, height=560, scrolling=True)
            full = f'<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>Barcodes</title></head><body>{page}</body></html>'
            st.download_button("⬇️ تحميل الملصقات (HTML)", full, file_name="barcode_labels.html", mime="text/html", key="bc_dl")
        else:
            st.info("اختر أصنافاً لعرض الملصقات.")
    with t2:
        q2 = st.text_input("🔍 ابحث عن الصنف", key="bc_q2")
        df2 = search_inv(q2).head(100)
        if df2.empty:
            st.info("لا توجد نتائج.")
        else:
            opts2 = {f"{r['part_number']} | {r['name']} | {r['model']} | {r['brand']} | {r['branch']} | باركود: {r['barcode']}": r
                     for _, r in df2.iterrows()}
            r = opts2[st.selectbox("الصنف", list(opts2.keys()), key="bc_item")]
            base = str(r["part_number"]).split("/")[0]
            st.write(f"الباركود الحالي: **{r['barcode']}** — " + ("✅ EAN-13 قابل للطباعة" if valid_ean13(r["barcode"]) else "⚠️ غير EAN-13 (يُمسح فقط، لا يُرسم)"))
            new = st.text_input("الباركود الجديد (كما هو مطبوع على العبوة، بدون مسافات)", key="bc_new").strip()
            a, b = st.columns(2)
            if a.button("💾 حفظ الباركود", type="primary"):
                if not new or " " in new:
                    st.error("أدخل باركوداً صحيحاً بدون مسافات.")
                elif not qdf("SELECT 1 FROM inventory WHERE barcode=? AND NOT (part_number=? OR part_number LIKE ?)",
                             (new, base, base + "/%")).empty:
                    st.error("هذا الباركود مستخدم لصنف آخر!")
                else:
                    run("UPDATE inventory SET barcode=? WHERE part_number=? OR part_number LIKE ?", (new, base, base + "/%"))
                    st.success("تم تحديث الباركود (لكل فروع هذا الصنف)."); st.rerun()
            if b.button("🔄 إعادة توليد الباركود الداخلي"):
                run("UPDATE inventory SET barcode=? WHERE part_number=? OR part_number LIKE ?",
                    (internal_barcode(r["id"]), base, base + "/%"))
                st.success("تمت إعادة التوليد."); st.rerun()

# ============================================================== الدخول والتشغيل
def login_screen():
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.markdown(f'<div class="login-card"><div style="font-size:3rem">🚗</div><h2>{html.escape(get_setting("store_name"))}</h2>'
                    f'<p>نظام إدارة المخازن والمبيعات — تسجيل الدخول</p></div>', unsafe_allow_html=True)
        wait = st.session_state.get("lock_until", 0) - time.time()
        if wait > 0:
            st.error(f"محاولات خاطئة كثيرة. حاول بعد {int(wait) + 1} ثانية."); return
        with st.form("login"):
            pw = st.text_input("كلمة المرور", type="password")
            if st.form_submit_button("دخول", type="primary"):
                if check_password(pw):
                    st.session_state["auth"] = True; st.session_state["fails"] = 0; st.rerun()
                st.session_state["fails"] = st.session_state.get("fails", 0) + 1
                if st.session_state["fails"] >= 5:
                    st.session_state["lock_until"] = time.time() + 60; st.session_state["fails"] = 0
                st.error("كلمة المرور غير صحيحة.")

st.set_page_config(page_title="نظام مخازن مرسيدس", page_icon="🚗", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)
init_db()
if not st.session_state.get("auth"):
    login_screen()
    st.stop()

PAGES = {"📈 لوحة التحكم": page_dashboard, "🔍 البحث الذكي": page_search, "🧾 المبيعات (POS)": page_pos,
         "🏷️ العروض والخصومات": page_offers, "📦 إدارة المخزون": page_inventory, "🔖 الباركود": page_barcode,
         "🔄 تحويل المخزون": page_transfer, "↩️ المرتجعات": page_returns,
         "🗂️ سجل الفواتير": page_history, "📊 التقارير": page_reports, "⚙️ الإعدادات": page_settings}
with st.sidebar:
    st.markdown(f'<div class="brand">🚗 {html.escape(get_setting("store_name"))}<small>نظام المخازن والمبيعات</small></div>', unsafe_allow_html=True)
    choice = st.radio("القائمة", list(PAGES.keys()), label_visibility="collapsed")
    st.divider()
    if st.button("🚪 تسجيل الخروج"):
        st.session_state.clear(); st.rerun()
    st.caption(datetime.date.today().strftime("%Y-%m-%d"))
PAGES[choice]()