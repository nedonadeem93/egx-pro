# -*- coding: utf-8 -*-
"""
عميل ESTHMR MCP — بيانات البورصة المصرية الرسمية (esthmr.com)
==============================================================
- توكن OAuth مع تجديد تلقائي بـ refresh_token (مش محتاج تسجيل تاني)
- كاش يومي: نفس الطلب في نفس يوم تداول = مجاني (بلاش من الرصيد)
- عدادات استخدام تحترم حدود الموقع: 300 طلب/يوم + 40 شركة مختلفة/يوم
- كل الاستدعاءات بترجع نص جاهز للعرض أو dict مفكوك بالـ parsers

الملفات اللي بيشتغل عليها (جنب الكود):
  esthmr_token.json  — التوكن (بيتحدث لوحده)
  esthmr_creds.json  — client_id بتاع التطبيق
  esthmr_usage.json  — عدادات اليوم (بيتصفر كل يوم)
  esthmr_cache.json  — كاش اليوم (بيتصفر كل يوم)

على Streamlit Cloud: نفس البيانات بتتنقرأ من قسم [esthmr] في st.secrets
أو متغيرات البيئة (ESTHMR_CLIENT_ID / ESTHMR_REFRESH_TOKEN) بدل الملفات —
يعني نفس الكود شغال محلياً وعلى Cloud من غير أي تعديل.
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    CAIRO = ZoneInfo("Africa/Cairo")
except Exception:
    CAIRO = None

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
MCP_URL = "https://esthmr.com/mcp"
TOKEN_URL = "https://esthmr.com/oauth/token"
RESOURCE = "https://esthmr.com/mcp"

BASE_DIR = Path(__file__).resolve().parent
TOKEN_FILE = BASE_DIR / "esthmr_token.json"
CREDS_FILE = BASE_DIR / "esthmr_creds.json"
USAGE_FILE = BASE_DIR / "esthmr_usage.json"
CACHE_FILE = BASE_DIR / "esthmr_cache.json"

DAILY_REQUESTS = 300
DAILY_COMPANIES = 40

UNIT = {"m": 1e6, "bn": 1e9, "trillion": 1e12}


# ---------------- st.secrets / بيئة (Streamlit Cloud) ----------------

_MEM_TOKEN = {}


def _secrets():
    """مفاتيح [esthmr] من st.secrets أو متغيرات البيئة — dict فاضي لو مفيش.
    بتقرأ secrets من Streamlit Cloud أو ملف .streamlit/secrets.toml محلياً،
    وبترجع {} بهدوء لو مفيش أي حاجة (عشان الوضع المحلي بالملفات يفضل شغال)."""
    out = {}
    try:
        import streamlit as st
        sec = dict(st.secrets.get("esthmr", {}) or {})
        out.update({k: v for k, v in sec.items() if v})
    except Exception:
        pass
    for env_key, key in (("ESTHMR_CLIENT_ID", "client_id"),
                         ("ESTHMR_REFRESH_TOKEN", "refresh_token"),
                         ("ESTHMR_ACCESS_TOKEN", "access_token")):
        v = os.environ.get(env_key)
        if v:
            out.setdefault(key, v)
    return out


class EsthmrQuota(RuntimeError):
    """خلص رصيد اليوم — التطبيق يكمل من غير esthmr."""
    pass


class EsthmrError(RuntimeError):
    pass


# ---------------- أدوات ملفات ----------------

def _load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save(path, obj):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
    except Exception:
        pass


# ---------------- التوكن ----------------

def load_token():
    """التوكن الحالي: الذاكرة ← الأحدث بين الكاش المحلي وst.secrets.
    الكاش المحلي بيكسب لو أحدث (فيه توكن اتجدد في تشغيل سابق)،
    وsecrets بيكسبوا لو مفيش ملف محلي (حالة Streamlit Cloud)."""
    global _MEM_TOKEN
    if _MEM_TOKEN.get("access_token") or _MEM_TOKEN.get("refresh_token"):
        return _MEM_TOKEN
    sec = _secrets()
    local = _load(TOKEN_FILE, {}) or {}
    if (local.get("refresh_token")
            and (local.get("_expires_at") or 0) >= (sec.get("_expires_at") or 0)):
        tok = local
    elif sec.get("refresh_token") or sec.get("access_token"):
        tok = sec
    else:
        tok = local
    if tok:
        _MEM_TOKEN = tok
    return tok


def refresh_token():
    """يحدّث access_token بـ refresh_token — ويرجّع التوكن الجديد."""
    global _MEM_TOKEN
    tok = load_token()
    sec = _secrets()
    creds = _load(CREDS_FILE, {}) or {}
    client_id = (sec.get("client_id") or creds.get("client_id")
                 or tok.get("client_id"))
    rt = tok.get("refresh_token")
    if not rt or not client_id:
        raise EsthmrError("مفيش refresh_token أو client_id — لازم إعادة ربط الحساب")
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": rt,
        "client_id": client_id,
        "resource": RESOURCE,
    }).encode()
    req = urllib.request.Request(
        TOKEN_URL, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            new = json.load(r)
    except urllib.error.HTTPError as e:
        raise EsthmrError(f"فشل تجديد التوكن (HTTP {e.code}): {e.read().decode()[:200]}")
    except Exception as e:
        raise EsthmrError(f"فشل تجديد التوكن: {e}")
    if "access_token" not in new:
        raise EsthmrError(f"رد تجديد غير متوقع: {str(new)[:200]}")
    new["_expires_at"] = time.time() + int(new.get("expires_in", 3600))
    if "refresh_token" not in new:
        new["refresh_token"] = rt
    _MEM_TOKEN = new          # في الذاكرة فوراً (حتى لو القرص مش قابل للكتابة)
    _save(TOKEN_FILE, new)    # حفظ محلي best-effort (على Cloud بيضيع مع إعادة التشغيل — عادي)
    return new


def _expired(tok, margin=180):
    exp = tok.get("_expires_at") or 0
    if not exp:  # ملف قديم من غير وقت انتهاء — اعتبره هينتهي
        return True
    return time.time() >= exp - margin


def get_access_token():
    tok = load_token()
    if not tok.get("access_token") or _expired(tok):
        tok = refresh_token()
    return tok["access_token"]


# ---------------- عدادات الاستخدام ----------------

def _today():
    dt = datetime.now(CAIRO) if CAIRO else datetime.utcnow()
    return dt.strftime("%Y-%m-%d")


def usage():
    u = _load(USAGE_FILE, {}) or {}
    if u.get("day") != _today():
        u = {"day": _today(), "requests": 0, "companies": []}
        _save(USAGE_FILE, u)
    return u


def remaining_requests():
    return max(0, DAILY_REQUESTS - usage()["requests"])


def remaining_companies():
    u = usage()
    return max(0, DAILY_COMPANIES - len(u.get("companies", [])))


def can_request(company=None):
    u = usage()
    if u.get("requests", 0) >= DAILY_REQUESTS:
        return False
    if company and company not in u.get("companies", []):
        if len(u.get("companies", [])) >= DAILY_COMPANIES:
            return False
    return True


def _record(company=None):
    u = usage()
    u["requests"] = u.get("requests", 0) + 1
    comps = u.setdefault("companies", [])
    if company and company not in comps:
        comps.append(company)
    _save(USAGE_FILE, u)


def status_line():
    """سطر حالة جاهز للعرض في الواجهة."""
    u = usage()
    return (f"🔋 رصيد esthmr النهاردة: {remaining_requests()}/{DAILY_REQUESTS} طلب"
            f" | شركات: {remaining_companies()}/{DAILY_COMPANIES}")


# ---------------- كاش يومي ----------------

def cache_get(key):
    c = _load(CACHE_FILE, {}) or {}
    e = c.get(key)
    if not e or e.get("day") != _today():
        return None
    return e.get("text")


def cache_set(key, text):
    c = _load(CACHE_FILE, {}) or {}
    today = _today()
    c = {k: v for k, v in c.items() if v.get("day") == today}
    c[key] = {"day": today, "text": text}
    _save(CACHE_FILE, c)


# ---------------- نواة MCP ----------------

def _post(payload, timeout=60):
    req = urllib.request.Request(
        MCP_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream",
                 "Authorization": f"Bearer {get_access_token()}",
                 "MCP-Protocol-Version": "2025-06-18",
                 "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


def _parse_reply(raw):
    if raw.strip().startswith("{"):
        data = json.loads(raw)
    else:
        m = re.findall(r"^data: (.+)$", raw, re.M)
        data = json.loads(m[-1]) if m else {}
    return data


def call_tool(name, args=None, company=None, use_cache=True, timeout=60):
    """تشغيل أداة MCP مع كاش يومي + عدادات + إعادة محاولة عند 401."""
    key = f"{name}|{json.dumps(args or {}, sort_keys=True, ensure_ascii=False)}"
    if use_cache:
        hit = cache_get(key)
        if hit is not None:
            return hit
    if not can_request(company):
        raise EsthmrQuota("خلص رصيد esthmr النهاردة (300 طلب / 40 شركة)")
    args = dict(args or {})
    args.setdefault("language", "en")
    payload = {"jsonrpc": "2.0", "id": 10, "method": "tools/call",
               "params": {"name": name, "arguments": args}}
    try:
        raw = _post(payload, timeout)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            refresh_token()
            raw = _post(payload, timeout)
        else:
            raise EsthmrError(f"MCP HTTP {e.code}: {e.read().decode()[:200]}")
    except EsthmrError:
        raise
    except Exception as e:
        raise EsthmrError(f"MCP اتصال: {e}")
    data = _parse_reply(raw)
    if "error" in data:
        raise EsthmrError(f"MCP error: {json.dumps(data['error'])[:300]}")
    res = data.get("result", {})
    text = "\n".join(c.get("text", "") for c in res.get("content", [])
                     if c.get("type") == "text")
    if res.get("isError"):
        raise EsthmrError(f"tool error: {text[:300]}")
    _record(company)
    cache_set(key, text)
    return text


# ---------------- غلاف جاهز ----------------

def snapshot(sym):
    return call_tool("company_snapshot", {"company": sym}, company=sym)


def filings(sym, limit=5):
    return call_tool("company_filings", {"company": sym, "limit": limit},
                     company=sym)


def insider(sym, days=90):
    return call_tool("insider_activity", {"company": sym, "days": days},
                     company=sym)


def upcoming(sym):
    return call_tool("upcoming_events", {"company": sym}, company=sym)


def market_overview_ar():
    return call_tool("market_overview", {"language": "ar"})


def investor_flows_ar(days=10):
    return call_tool("investor_flows", {"days": days, "language": "ar"})


def screen(**kw):
    kw.setdefault("language", "en")
    return call_tool("screen_stocks", kw)


# ---------------- مفككات النصوص (parsers) ----------------

def _num(s):
    try:
        return float(str(s).replace(",", "").replace("−", "-"))
    except Exception:
        return None


def _egp(val, unit):
    m = UNIT.get(unit, 1.0)
    v = val * m
    if v >= 1e9:
        return f"{v/1e9:.2f} مليار ج"
    if v >= 1e6:
        return f"{v/1e6:.1f} مليون ج"
    return f"{v:,.0f} ج"


def parse_snapshot(text):
    """يستخرج الأرقام المفتاحية من رد company_snapshot."""
    t = text.replace("−", "-")  # الشرطة السالبة الطويلة U+2212
    out = {}

    m = re.search(r"·\s*([A-Za-z &,']+[A-Za-z&'])\s+—\s+as of", t)
    if m:
        out["sector"] = m.group(1).strip()

    m = re.search(r"Market value EGP ([\d.]+)\s*(m|bn|trillion)", t)
    if m:
        out["market_cap"] = _egp(float(m.group(1)), m.group(2))

    m = re.search(r"high EGP ([\d.]+), low EGP ([\d.]+); the latest close is "
                  r"(-?[\d.]+)% from the high and \+?(-?[\d.]+)% from the low", t)
    if m:
        out["w52_high"] = float(m.group(1))
        out["w52_low"] = float(m.group(2))
        out["pct_from_high"] = float(m.group(3))
        out["pct_from_low"] = float(m.group(4))

    m = re.search(r"([\d.,]+)× the median volume", t)
    if m:
        out["rel_volume"] = _num(m.group(1))

    m = re.search(r"P/E ([\d.]+)", t)
    if m:
        out["pe"] = float(m.group(1))

    m = re.search(r"P/B ([\d.]+)", t)
    if m:
        out["pb"] = float(m.group(1))
    m = re.search(r"Return on equity ([\d.]+)%", t)
    if m:
        out["roe"] = float(m.group(1))
    m = re.search(r"Debt to equity ([\d.]+)", t)
    if m:
        out["de"] = float(m.group(1))
    m = re.search(r"Dividend yield ([\d.]+)%", t)
    if m:
        out["div_yield"] = float(m.group(1))
    m = re.search(r"Earnings per share EGP ([\d.]+)", t)
    if m:
        out["eps"] = float(m.group(1))

    m = re.search(r"Net income,? ([^:]+): EGP ([\d.]+)\s*(m|bn), "
                  r"\+?(-?[\d.]+)% against the same span a year earlier", t)
    if m:
        out["ni_period"] = m.group(1).strip()
        out["ni_value"] = _egp(float(m.group(2)), m.group(3))
        out["ni_growth"] = float(m.group(4))

    m = re.search(r"([\d,]+) bought and ([\d,]+) sold over the last 30 days, "
                  r"net (-?[\d,]+) shares", t)
    if m:
        out["ins30_buys"] = int(m.group(1).replace(",", ""))
        out["ins30_sells"] = int(m.group(2).replace(",", ""))
        out["ins30_net"] = int(m.group(3).replace(",", ""))
    m = re.search(r"([\d,]+) bought and ([\d,]+) sold over the last 90 days, "
                  r"net (-?[\d,]+) shares", t)
    if m:
        out["ins90_buys"] = int(m.group(1).replace(",", ""))
        out["ins90_sells"] = int(m.group(2).replace(",", ""))
        out["ins90_net"] = int(m.group(3).replace(",", ""))

    m = re.search(r"Largest shareholder on record:\s*(.+?),\s*([\d.]+)%", t)
    if m:
        out["major_holder"] = m.group(1).strip()
        out["major_holder_pct"] = float(m.group(2))

    out["latest_filings"] = []
    for line in t.splitlines():
        fm = re.match(r"^•\s*Filed\s+(.+?)(?:\s*\((.+?)\))?:\s*(.+)$", line.strip())
        if fm:
            out["latest_filings"].append(
                {"date": fm.group(1).strip(), "kind": (fm.group(2) or "").strip(),
                 "title": fm.group(3).strip()})
    return out


def parse_filings(text):
    """رد company_filings → قايمة (date, kind, title, url)."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("•"):
            continue
        m = re.match(r"^•\s*(\d{1,2}\s+\w+\s+\d{4})(?:\s*·\s*([^—·]+?))?\s*—\s*"
                     r"(.+?)(?:\s*·\s*(https://\S+))?\s*$", line)
        if m:
            rows.append({"date": m.group(1).strip(),
                         "kind": (m.group(2) or "").strip(),
                         "title": m.group(3).strip(),
                         "url": (m.group(4) or "").strip()})
    return rows


def parse_insider(text):
    """رد insider_activity → ملخص + صفوف."""
    t = text.replace("−", "-")
    out = {}
    m = re.search(r"In this window:\s*([\d,]+) bought,\s*([\d,]+) sold on "
                  r"([\d,]+) sessions; net (-?[\d,]+) shares", t)
    if m:
        out["buys"] = int(m.group(1).replace(",", ""))
        out["sells"] = int(m.group(2).replace(",", ""))
        out["sessions"] = int(m.group(3).replace(",", ""))
        out["net"] = int(m.group(4).replace(",", ""))
    rows = []
    for line in t.splitlines():
        line = line.strip()
        if not line.startswith("•"):
            continue
        m = re.match(r"^•\s*(.+?\d{4})\s*·\s*(.+?)\s*·\s*(bought|sold)\s*"
                     r"([\d,]+) shares", line)
        if m:
            rows.append({"date": m.group(1).strip(), "who": m.group(2).strip(),
                         "side": m.group(3), "shares": int(m.group(4).replace(",", ""))})
    out["rows"] = rows
    return out


def parse_screen(text):
    """رد screen_stocks → صفوف (sym, desc, traded_value, market_cap)."""
    t = text.replace("−", "-")
    rows, total = [], None
    m = re.search(r"تحققها ([\d,]+) شركة|([\d,]+) companies? match", t)
    if m:
        raw = m.group(1) or m.group(2) or "0"
        total = int(raw.replace(",", ""))
    for line in t.splitlines():
        m = re.match(r"^\d+\.\s*([A-Z0-9]{2,10})\s*·\s*(.+?)\s*—\s*(.+)$",
                     line.strip())
        if not m:
            continue
        sym, desc, tail = m.group(1), m.group(2).strip(), m.group(3)
        row = {"sym": sym, "desc": desc, "traded_value": 0.0, "market_cap": None}
        tm = (re.search(r"value traded EGP ([\d.]+)\s*(m|bn|trillion)", tail)
              or re.search(r"traded value EGP ([\d.]+)\s*(m|bn|trillion)", tail))
        if tm:
            row["traded_value"] = float(tm.group(1)) * UNIT[tm.group(2)]
        mm = re.search(r"market value EGP ([\d.]+)\s*(m|bn|trillion)", tail)
        if mm:
            row["market_cap"] = float(mm.group(1)) * UNIT[mm.group(2)]
        rows.append(row)
    return rows, total


def insider_signal(est):
    """يحوّل أرقام المطلعين لإشارة درج (+1/+2/-1) وسبب نصي."""
    if not est:
        return 0, None
    buys = est.get("ins90_buys")
    sells = est.get("ins90_sells")
    net = est.get("ins90_net")
    if buys is None or net is None:
        return 0, None
    if net > 0 and buys >= 5:
        return 2, (f"✅ المطلعين مشترون صافي ({buys} شراء) — "
                   f"+{net:,} سهم في 90 يوم")
    if net > 0 and buys >= 2:
        return 1, (f"✅ المطلعين مشترون صافي ({buys} شراء / {sells} بيع) — "
                   f"+{net:,} سهم في 90 يوم")
    if net < 0 and sells >= 10:
        return -1, (f"⚠️ المطلعين بائعون صافي ({sells} بيع / {buys} شراء) — "
                    f"{net:,} سهم في 90 يوم")
    if net < 0 and sells >= 3:
        return 0, (f"ℹ️ ميل بيع خفيف من المطلعين ({sells} بيع / {buys} شراء) — "
                   f"{net:,} سهم في 90 يوم")
    return 0, (f"ℹ️ نشاط مطلعين هادي ({buys} شراء / {sells} بيع) في 90 يوم")
