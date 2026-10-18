# -*- coding: utf-8 -*-
"""
EGX-Pro — محلل البورصة المصرية 🇪🇬📈 (نسخة TradingView الكاملة)
================================================================
كل الأسعار والمؤشرات (RSI/MACD/SMA/بولينجر/مدى سنة) من TradingView مباشرة
عبر Scanner API — مفيش أي اعتماد على Yahoo خالص.
طلب واحد بيجيب السوق كله (296 سهم) بكل المؤشرات محسوبة من TradingView نفسه.
طبقة بيانات رسمية إضافية من esthmr.com:
  🕵️ تعاملات المطلعين  📢 الإفصاحات  🏢 أساسيات  🌐 نظرة سوق (تدفقات مستثمرين)
الشارت: شارت TradingView التفاعلي مدمج جوه التطبيق.

مستقل 100%: كل ملفاته (توكن/كاش/قايمة) في نفس مجلده.
تشغيل:  streamlit run egx_pro.py
"""
import os
import json
import time
import datetime

import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="EGX-Pro — محلل البورصة المصرية",
                   page_icon="📈", layout="wide")

import requests
import pandas as pd
import numpy as np

# ============ طبقة esthmr (بيانات رسمية) ============

try:
    import esthmr_client as ec
    HAS_ESTHMR = True
except Exception:
    ec = None
    HAS_ESTHMR = False

try:
    from zoneinfo import ZoneInfo
    CAIRO = ZoneInfo("Africa/Cairo")
except Exception:
    CAIRO = None


def now_cairo():
    if CAIRO:
        return datetime.datetime.now(CAIRO)
    return datetime.datetime.utcnow()

# ============ طبقة TradingView Scanner ============
# نفس الـ API اللي بيشغّل سكرينر موقع TradingView — بدون مكتبات خارجية.
# طلب واحد = السوق كامل بكل المؤشرات محسوبة من TradingView نفسه.

TV_SCAN_URL = "https://scanner.tradingview.com/egypt/scan"
TV_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Origin": "https://www.tradingview.com",
    "Content-Type": "application/json",
}
TV_TTL = 120  # ثانية — كاش السوق (السعر اللحظي بتأخير ~15 د زي كل المصادر المجانية)

# أعمدة API — كلها اتأكدنا منها عملياً على سوق egypt
TV_COLUMNS = [
    "name", "description", "close", "open", "high", "low", "volume", "change",
    "RSI", "MACD.macd", "MACD.signal", "MACD.macd[1]", "MACD.signal[1]",
    "SMA50", "SMA100", "SMA200", "EMA50", "EMA200",
    "BB.upper", "BB.lower", "BB.lower[1]",
    "price_52_week_high", "price_52_week_low",
    "average_volume_30d_calc", "average_volume_10d_calc",
    "relative_volume_10d_calc",
    "Perf.W", "Perf.1M", "Perf.3M", "Perf.Y",
    "type", "currency", "close[1]",
    "market_cap_basic", "price_earnings_ttm", "dividends_yield_current",
    "sector", "industry", "update_mode",
]

TV_RENAME = {
    "name": "sym", "description": "desc", "volume": "vol", "change": "chg",
    "RSI": "rsi",
    "MACD.macd": "macd", "MACD.signal": "macd_sig",
    "MACD.macd[1]": "macd_p", "MACD.signal[1]": "sig_p",
    "SMA50": "sma50", "SMA100": "sma100", "SMA200": "sma200",
    "EMA50": "ema50", "EMA200": "ema200",
    "BB.upper": "bb_u", "BB.lower": "bb_l", "BB.lower[1]": "bb_l_p",
    "price_52_week_high": "w52h", "price_52_week_low": "w52l",
    "average_volume_30d_calc": "avg_vol30", "average_volume_10d_calc": "avg_vol10",
    "relative_volume_10d_calc": "relv",
    "Perf.W": "perf_w", "Perf.1M": "perf_1m", "Perf.3M": "perf_3m",
    "Perf.Y": "perf_y",
    "close[1]": "close_p", "market_cap_basic": "mcap",
    "price_earnings_ttm": "pe", "dividends_yield_current": "divy",
}

TV_NUMERIC = ["close", "open", "high", "low", "vol", "chg", "rsi",
              "macd", "macd_sig", "macd_p", "sig_p",
              "sma50", "sma100", "sma200", "ema50", "ema200",
              "bb_u", "bb_l", "bb_l_p", "w52h", "w52l",
              "avg_vol30", "avg_vol10", "relv",
              "perf_w", "perf_1m", "perf_3m", "perf_y",
              "close_p", "mcap", "pe", "divy"]

SYMBOL_DESC = {}
ALL_STOCKS = []


def _tv_scan(columns, tickers=None, sort_by="volume", limit=600):
    """طلب واحد لسكانر TradingView — بيرجّع DataFrame خام."""
    payload = {
        "filter": [{"left": "type", "operation": "equal", "right": "stock"}],
        "options": {"lang": "en"},
        "markets": ["egypt"],
        "symbols": {"query": {"types": []}, "tickers": tickers or []},
        "columns": columns,
        "sort": {"sortBy": sort_by, "sortOrder": "desc"},
        "range": [0, limit],
    }
    r = requests.post(TV_SCAN_URL, json=payload, timeout=25, headers=TV_HEADERS)
    r.raise_for_status()
    js = r.json()
    rows = []
    for rec in js.get("data", []):
        d = dict(zip(columns, rec.get("d", [])))
        d["ticker"] = rec.get("s", "")
        rows.append(d)
    return pd.DataFrame(rows)


def _clean_market_df(df):
    """تنظيف DataFrame السوق: أسماء أعمدة نظيفة + أرقام + فلترة الأسهم بس."""
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.rename(columns=TV_RENAME)
    for c in TV_NUMERIC:
        if c not in df.columns:
            df[c] = None
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if "sym" not in df.columns:
        return pd.DataFrame()
    df["sym"] = df["sym"].astype(str).str.upper().str.strip()
    df = df[(df["sym"] != "") & (df["sym"] != "NAN")]
    df = df[df["sym"].str.isalnum()]
    if "type" in df.columns:
        df = df[df["type"] == "stock"]
    df = df.dropna(subset=["close"])
    df = df[df["close"] > 0]
    df = df.drop_duplicates(subset=["sym"])
    return df.reset_index(drop=True)


def _register_desc(df):
    try:
        if "desc" in df.columns:
            SYMBOL_DESC.update(dict(zip(df["sym"], df["desc"].astype(str))))
    except Exception:
        pass


def tv_market_df(force=False):
    """السوق كامل من TradingView — طلب واحد، كاش دقيقتين في الجلسة.
    لو الشبكة فشلت بيرجّع آخر كاش موجود بدل ما يقفل."""
    key = "_tv_mkt"
    now = time.time()
    c = st.session_state.get(key)
    if not force and c is not None and now - c.get("ts", 0) < TV_TTL \
            and c.get("df") is not None and not c["df"].empty:
        _register_desc(c["df"])
        return c["df"]
    try:
        raw = _tv_scan(TV_COLUMNS)
        df = _clean_market_df(raw)
    except Exception:
        df = pd.DataFrame()
    if df.empty:
        # الشبكة وقعت — رجّع آخر كاش شغال (ولو قديم شوية)
        if c is not None and c.get("df") is not None and not c["df"].empty:
            _register_desc(c["df"])
            return c["df"]
        return pd.DataFrame()
    _register_desc(df)
    st.session_state[key] = {"ts": now, "df": df}
    return df


def _f(rec, col):
    """قراءة رقم آمنة من صف (dict) — بترجّع None لو ناقص أو NaN."""
    v = rec.get(col)
    try:
        v = float(v)
        return None if pd.isna(v) else v
    except Exception:
        return None


def v_from_record(rec):
    """تحويل صف السوق لقاموس قيم نظيفة (كلها أرقام أو None) — القلب المشترك
    بين المسح وتحليل السهم الواحد."""
    v = {c: _f(rec, c) for c in TV_NUMERIC}
    v["price"] = v["close"]  # اسم موحد تستخدمه دوال القرار
    return v


def tv_raw_for(symbol):
    """بيانات سهم واحد من كاش السوق، أو استعلام مباشر لو مش موجود فيه."""
    symbol = symbol.strip().upper()
    df = tv_market_df()
    if df is not None and not df.empty and symbol in set(df["sym"]):
        return df[df["sym"] == symbol].iloc[0].to_dict()
    try:
        dfx = _tv_scan(TV_COLUMNS, tickers=[f"EGX:{symbol}"],
                       sort_by="volume", limit=5)
        dfx = _clean_market_df(dfx)
        if not dfx.empty:
            return dfx.iloc[0].to_dict()
    except Exception:
        pass
    return None


def sr_levels(v):
    """أقرب دعم ومقاومة من مستويات فنية حقيقية محسوبة من TradingView:
    بولينجر + متوسطات متحركة + مدى السنة."""
    price = v["price"]
    if price is None:
        return [], []
    sup_c = [x for x in [v["bb_l"], v["ema200"], v["sma200"], v["w52l"]]
             if x is not None and x < price * 0.999]
    res_c = [x for x in [v["bb_u"], v["ema50"], v["sma50"], v["sma200"], v["w52h"]]
             if x is not None and x > price * 1.001]
    supports = sorted({round(x, 2) for x in sup_c}, reverse=True)
    resistances = sorted({round(x, 2) for x in res_c})
    return supports, resistances


def session_info(v):
    """حالة سعر السهم: من جلسة النهاردة ولا آخر جلسة؟
    بيرجّع (stale_bool, note, p_time)."""
    today = now_cairo().date()
    d = today
    while d.weekday() in (4, 5):  # الجمعة والسبت عطلة البورصة
        d -= datetime.timedelta(days=1)
    last_sess = d
    vol = v["vol"] or 0
    wd = today.weekday()
    if wd not in (4, 5) and vol > 0:
        return False, "", now_cairo().strftime("%m-%d %H:%M") + " (جلسة النهاردة)"
    if wd not in (4, 5) and vol <= 0:
        note = ("ℹ️ مفيش تداول مسجّل للسهم النهاردة لحد دلوقتي "
                "(السوق بيفتح 10:00 ص) — السعر من آخر جلسة")
        return False, note, last_sess.strftime("%Y-%m-%d")
    note = (f"ℹ️ النهاردة عطلة رسمية (جمعة/سبت) — السعر من آخر جلسة "
            f"{last_sess.strftime('%Y-%m-%d')}")
    return True, note, last_sess.strftime("%Y-%m-%d")


# ============ السيولة ============

def fmt_num(x):
    x = float(x)
    if x >= 1e9:
        return f"{x/1e9:.2f} مليار"
    if x >= 1e6:
        return f"{x/1e6:.1f} مليون"
    if x >= 1e3:
        return f"{x/1e3:.1f} ألف"
    return f"{x:,.0f}"


def liquidity_from_row(v):
    """تقييم السيولة من متوسط 30 جلسة بتاع TradingView — نفس عتبات التقرير."""
    price = v["price"] or 0.0
    avg_vol = v["avg_vol30"] or 0.0
    avg_value = avg_vol * price
    today_value = (v["vol"] or 0.0) * price
    rel = v["relv"] or 0.0

    if avg_value >= 100e6:
        rate = "🟢 ممتازة"
    elif avg_value >= 25e6:
        rate = "🟢 جيدة"
    elif avg_value >= 5e6:
        rate = "🟡 متوسطة"
    elif avg_value > 0:
        rate = "🔴 ضعيفة"
    else:
        rate = "⚪ مفيش بيانات"
    return dict(avg_vol=avg_vol, avg_value=avg_value,
                today_value=today_value, rate=rate, rel=rel)

# ============ القرار (نفس نظام الدرج + إشارة المطلعين) ============

def decide_tv(v, supports, resistances, liq, est=None):
    """نفس نظام الدرج القديم بالحرف — بس المدخلات كلها محسوبة من TradingView."""
    price = v["price"]
    rsi = v["rsi"]
    score, reasons = 0, []

    # 1) RSI — +2 تشبع بيعي / −2 تشبع شرائي
    if rsi is not None:
        if rsi < 30:
            score += 2
            reasons.append("✅ RSI تحت 30 (تشبع بيعي)")
        elif rsi > 70:
            score -= 2
            reasons.append("⚠️ RSI فوق 70 (تشبع شرائي)")

    # 2) تقاطع MACD صاعد جديد (الإغلاق السابق كان تحت الإشارة والآن فوقها) — +2
    macd, sig = v["macd"], v["macd_sig"]
    if macd is not None and sig is not None and macd > sig:
        pm, ps = v["macd_p"], v["sig_p"]
        if pm is not None and ps is not None and pm <= ps:
            score += 2
            reasons.append("✅ تقاطع MACD صاعد جديد")

    # 3) الاتجاه العام: السعر فوق SMA50 و SMA50 فوق SMA200 — +1 / العكس −1
    s50, s200 = v["sma50"], v["sma200"]
    if s50 is not None and s200 is not None:
        if price > s50 > s200:
            score += 1
            reasons.append("✅ الاتجاه العام صاعد")
        elif price < s50 < s200:
            score -= 1
            reasons.append("⚠️ الاتجاه العام هابط")

    below = [s for s in supports if s < price]
    above = [r for r in resistances if r > price]
    support = max(below) if below else round(price * 0.95, 2)
    resistance = min(above) if above else round(price * 1.05, 2)
    real_support = bool(below)

    # 4) ملاصقة دعم (في حدود 2%) — +2
    near_support = (price - support) / price <= 0.02
    if near_support:
        score += 2
        reasons.append(f"✅ السعر ملاصق لدعم {support}")

    # 5) ارتداد من البولينجر السفلي (إغلاق أمس تحته والآن فوقه) — +1
    bb_l, bb_l_p = v["bb_l"], v["bb_l_p"]
    if bb_l is not None and bb_l_p is not None and v["close_p"] is not None:
        if v["close_p"] <= bb_l_p and price > bb_l:
            score += 1
            reasons.append("✅ ارتداد من البولينجر السفلي")

    # 6) حجم غير عادي / سيولة ضعيفة (ملاحظات بدون نقاط)
    relv = v["relv"]
    if relv is not None and relv >= 2:
        reasons.append(f"🔥 تداول النهاردة {relv:.1f}× المتوسط")
    if 0 < liq["avg_value"] < 5e6:
        reasons.append("⚠️ سيولة ضعيفة — التنفيذ صعب")

    # ===== إشارة المطلعين من esthmr (بيانات رسمية) =====
    if est:
        sig_i, why = ec.insider_signal(est)
        if sig_i:
            score += sig_i
        if why:
            reasons.append(why)
        rv = est.get("rel_volume")
        if rv and rv >= 2:
            reasons.append(f"🔥 حجم غير عادي: {rv}× متوسط الـ20 جلسة (esthmr)")

    # منطقة الدخول + وقف الخسارة + عائد/مخاطرة — نفس منطق القديم
    if near_support:
        entry = (round(support * 1.001, 2), round(price, 2))
        entry_note = "عند الدعم — دخول مناسب دلوقتي"
        ref_price = price
    else:
        entry = (round(support, 2), round(support * 1.02, 2))
        if real_support:
            entry_note = f"استنى السعر ينزل لمنطقة {entry[0]} - {entry[1]}"
        else:
            entry_note = (f"مفيش دعم واضح قريب — المنطقة {entry[0]} - {entry[1]} "
                          "محسوبة تحته، والأفضل تستنى دعم حقيقي يتكوّن")
        ref_price = entry[1]

    stop_loss = round(support * 0.97, 2)
    rr = round((resistance - ref_price) / max(ref_price - stop_loss, 0.01), 2)

    if score >= 4:
        decision = "🟢 شراء"
    elif score >= 2:
        decision = "🟡 شراء محتمل"
    elif score <= -2:
        decision = "🔴 بيع / ابتعاد"
    else:
        decision = "⚪ محايد — استنى"

    rsi_out = round(rsi, 1) if rsi is not None else None
    return dict(support=support, resistance=resistance, entry=entry,
                entry_note=entry_note, stop_loss=stop_loss, rr=rr,
                decision=decision, score=score, reasons=reasons, rsi=rsi_out)


def esthmr_enrich(symbol):
    """طبقة esthmr للسهم الواحد: snapshot + آخر الإفصاحات.
    بترجّع (est_dict, filings_list, note)."""
    if not HAS_ESTHMR:
        return None, [], "مكتبة esthmr مش موجودة جنب التطبيق"
    est, rows, note = None, [], ""
    try:
        est = ec.parse_snapshot(ec.snapshot(symbol))
    except ec.EsthmrQuota:
        return None, [], "خلص رصيد esthmr النهاردة — التقرير من غير طبقة esthmr"
    except Exception as e:
        note = f"esthmr مش متاح دلوقتي ({str(e)[:60]})"
    try:
        rows = ec.parse_filings(ec.filings(symbol, 5))
    except ec.EsthmrQuota:
        pass
    except Exception:
        pass
    return est, rows, note


def analyze(symbol):
    """تحليل سهم واحد — كل البيانات من TradingView + طبقة esthmr الرسمية."""
    symbol = symbol.strip().upper()
    raw = tv_raw_for(symbol)
    if raw is None:
        raise ValueError("مفيش بيانات من TradingView — اتأكد من الرمز")

    v = v_from_record(raw)
    if v["price"] is None:
        raise ValueError("مفيش سعر من TradingView — اتأكد من الرمز")

    # طبقة esthmr الرسمية (كاش يومي — طلب واحد لكل مصدر)
    est, filings_rows, est_note = esthmr_enrich(symbol)

    supports, resistances = sr_levels(v)
    liq = liquidity_from_row(v)
    d = decide_tv(v, supports, resistances, liq, est=est)
    stale, stale_note, p_time = session_info(v)

    closes_line = "—"
    if v["close_p"] is not None:
        diff = v["price"] - v["close_p"]
        closes_line = (f"`{v['close_p']:.2f} (إغلاق آخر جلسة) → "
                       f"{v['price']:.2f} الآن ({diff:+.2f})`")

    try:
        um = raw.get("update_mode")
        if um is not None and pd.isna(um):
            um = None
    except Exception:
        um = None
    um = str(um) if um is not None else ""
    if "delayed" in um:
        src_note = "TradingView — تدفق متأخر ~15 دقيقة (المعيار للمصادر المجانية)"
    else:
        src_note = "TradingView"

    return dict(symbol=symbol, price=v["price"], psrc=src_note, p_time=p_time,
                stale=stale, stale_note=stale_note,
                last_d=p_time,
                quality_notes=[],
                closes_line=closes_line,
                rsi=d["rsi"], support=d["support"],
                resistance=d["resistance"], decision=d["decision"],
                entry=d["entry"], entry_note=d["entry_note"],
                stop_loss=d["stop_loss"], target=d["resistance"],
                rr=d["rr"], reasons=d["reasons"], score=d["score"],
                v=v, liq=liq, supports=supports, resistances=resistances,
                est=est, filings_rows=filings_rows, est_note=est_note)


def deep_row_tv(sym, v):
    """صف تحليل عميق لسهم من بيانات TradingView — نفس شكل صف المسح القديم."""
    try:
        if v["price"] is None:
            return None
        if (v["vol"] or 0) <= 0 and (v["avg_vol30"] or 0) <= 0:
            # سهم موقوف / مفيش تداول خالص — نعرضه بدون تحليل بأمانة
            return dict(sym=sym, price=v["price"], chg=v["chg"], val=0.0,
                        mcap=v["mcap"], score=0,
                        dec="⚪ بدون تداول حديث — التحليل يحتاج تداول فعلي", d=None)
        supports, resistances = sr_levels(v)
        liq = liquidity_from_row(v)
        d = decide_tv(v, supports, resistances, liq, est=None)
        val = v["price"] * (v["vol"] or 0)
        if val <= 0:
            val = liq["avg_value"]
        return dict(sym=sym, price=v["price"], chg=v["chg"], val=val,
                    mcap=v["mcap"], score=d["score"], dec=d["decision"], d=d)
    except Exception:
        return None


# ============ جدول النتايج ============

HEADERS = ["السهم", "السعر", "التغير", "سيولة اليوم", "القيمة السوقية",
           "الدرج", "القرار", "الدعم", "المقاومة", "منطقة الدخول",
           "وقف الخسارة", "R/R", "ملاحظات"]


def build_table(res):
    if res is None or not len(res):
        return pd.DataFrame(columns=HEADERS)
    res = res.sort_values(["score", "val"], ascending=False)
    rows = []
    for r in res.itertuples():
        d = r.d
        mcap = "—"
        try:
            mcap = fmt_num(r.mcap) + " ج" if r.mcap else "—"
        except Exception:
            mcap = "—"
        if d is None:
            chg_s = f"{r.chg:+.1f}%" if r.chg is not None else "—"
            rows.append([r.sym, f"{r.price:.2f}", chg_s, fmt_num(r.val) if r.val else "—",
                         mcap, "—", r.dec, "—", "—", "—", "—", "—",
                         "⚪ بدون تداول حديث"])
            continue
        notes = " • ".join(d["reasons"][:3]) if d["reasons"] else "—"
        rows.append([
            r.sym, f"{r.price:.2f}", f"{r.chg:+.1f}%",
            fmt_num(r.val), mcap, f"{r.score:+d}", r.dec,
            f"{d['support']:.2f}", f"{d['resistance']:.2f}",
            f"{d['entry'][0]} – {d['entry'][1]}",
            f"{d['stop_loss']:.2f}", f"{d['rr']:.1f}", notes])
    return pd.DataFrame(rows, columns=HEADERS)


# ============ شارت TradingView المدمج ============

def tradingview_widget(symbol, height=520, theme="dark"):
    """شارت TradingView التفاعلي الحقيقي — شموع + RSI، تكبير وتصغير من جواه."""
    cfg = {
        "autosize": True,
        "symbol": f"EGX:{symbol}",
        "interval": "D",
        "timezone": "Africa/Cairo",
        "theme": theme,
        "style": "1",
        "locale": "en",
        "enable_publishing": False,
        "hide_side_toolbar": True,
        "allow_symbol_change": False,
        "withdateranges": True,
        "studies": ["RSI@tv-basicstudies"],
        "support_host": "https://www.tradingview.com",
    }
    import json as _json
    html = f"""
    <div class="tradingview-widget-container" style="height:{height}px">
      <div class="tradingview-widget-container__widget" style="height:{height}px"></div>
      <script type="text/javascript"
        src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js" async>
      {_json.dumps(cfg, ensure_ascii=False)}
      </script>
    </div>
    """
    components.html(html, height=height + 12, scrolling=False)


# ============ التقرير ============

def _esthmr_report_sections(r):
    """أقسام esthmr في تقرير السهم: أساسيات + مطلعين + إفصاحات."""
    est, rows, note = r.get("est"), r.get("filings_rows", []), r.get("est_note", "")
    out = []
    if note and not est:
        out += ["---", f"ℹ️ *{note}*"]
        return out
    if not est and not rows:
        return out

    if est:
        bits = []
        if est.get("sector"):
            bits.append(f"🏭 **القطاع:** {est['sector']}")
        if est.get("market_cap"):
            bits.append(f"💰 **القيمة السوقية:** {est['market_cap']}")
        if est.get("pe"):
            bits.append(f"📐 **P/E:** {est['pe']}")
        if est.get("div_yield"):
            bits.append(f"💵 **عائد التوزيعات:** {est['div_yield']}%")
        if est.get("roe"):
            bits.append(f"📈 **ROE:** {est['roe']}%")
        if est.get("w52_high") and est.get("w52_low"):
            ph = est.get("pct_from_high")
            pos = f" (السعر {ph:+.1f}% من القمة)" if ph is not None else ""
            bits.append(f"📊 **مدى سنة:** {est['w52_low']} – {est['w52_high']}{pos}")
        if est.get("ni_value"):
            g = est.get("ni_growth")
            gs = f" بنمو **{g:+.2f}%**" if g is not None else ""
            bits.append(f"🧾 **آخر نتائج:** {est['ni_value']}{gs} "
                        f"({est.get('ni_period', '')})")
        if est.get("major_holder"):
            bits.append(f"👑 **أكبر مساهم:** {est['major_holder']} "
                        f"({est.get('major_holder_pct', '?')}%)")
        if bits:
            out += ["---", "### 🏢 أساسيات من esthmr (بيانات رسمية)"]
            out += [f"- {b}" for b in bits]

    sig, why = ec.insider_signal(est) if (ec and est) else (0, None)
    if est and (est.get("ins90_buys") is not None):
        out += ["---", "### 🕵️ تعاملات المطلعين (90 يوم)"]
        if why:
            out.append(why)
        f30b, f30s, f30n = (est.get("ins30_buys"), est.get("ins30_sells"),
                            est.get("ins30_net"))
        if f30b is not None:
            out.append(f"- آخر 30 يوم: {f30b} شراء / {f30s} بيع "
                       f"(صافي {f30n:+,} سهم)")
    if rows:
        out += ["---", "### 📢 آخر الإفصاحات (من البورصة)"]
        for f in rows[:5]:
            kind = f" ` {f['kind']} ` " if f.get("kind") else " "
            url = f" — [المصدر ↗]({f['url']})" if f.get("url") else ""
            out.append(f"- **{f['date']}**{kind}{f['title']}{url}")
    return out


def _tv_fundamentals_lines(v):
    """أساسيات مجانية فورية من TradingView (بدون رصيد esthmr)."""
    bits = []
    if v.get("sector"):
        ind = f" / {v['industry']}" if v.get("industry") else ""
        bits.append(f"🏭 **القطاع:** {v['sector']}{ind}")
    if v.get("mcap"):
        bits.append(f"💰 **القيمة السوقية:** {fmt_num(v['mcap'])} ج")
    if v.get("pe"):
        bits.append(f"📐 **P/E:** {v['pe']:.1f}")
    if v.get("divy"):
        bits.append(f"💵 **عائد التوزيعات:** {v['divy']:.1f}%")
    if v.get("w52l") is not None and v.get("w52h") is not None:
        rng = v["w52h"] - v["w52l"]
        if rng > 0:
            pos = (v["price"] - v["w52l"]) / rng * 100
            bits.append(f"📊 **مدى سنة:** {v['w52l']:.2f} – {v['w52h']:.2f} "
                        f"(السعر في {pos:.0f}% من المدى)")
    if v.get("perf_y") is not None:
        bits.append(f"🗓 **عائد سنة:** {v['perf_y']:+.1f}%")
    return bits


def report(r):
    liq = r["liq"]
    v = r["v"]
    desc = SYMBOL_DESC.get(r["symbol"], "")
    head = f"### 📊 {r['symbol']}" + (f" — *{desc}*" if desc else "")
    lines = [
        head,
        (f"**💰 السعر:** {r['price']:.2f} ج 🕒 *({r['p_time']})*"
         f" | **RSI:** {r['rsi'] if r['rsi'] is not None else '—'}"
         f" | **الدرج:** {r['score']:+d}"),
        f"🗂 **المصدر:** {r['psrc']}",
    ]
    if r["stale_note"]:
        lines.append(r["stale_note"])
    lines += [
        f"## {r['decision']}", "---",
        f"🛡️ **الدعم (أقرب مستوى فني):** {r['support']}",
        f"⚔️ **المقاومة (الهدف):** {r['resistance']}",
        f"🎯 **منطقة الدخول:** {r['entry'][0]} → {r['entry'][1]}",
        f"*{r['entry_note']}*",
        (f"🚨 **وقف الخسارة:** {r['stop_loss']} | "
         f"⚖️ عائد/مخاطرة: {r['rr']} *(محسوبة على خطة الدخول)*"),
        "---",
        f"💧 **السيولة:** {liq['rate']} — متوسط {fmt_num(liq['avg_value'])} ج/يوم (30 جلسة)",
        f"📦 **الكميات:** {fmt_num(liq['avg_vol'])} سهم/يوم",
    ]
    tv_bits = _tv_fundamentals_lines(v)
    if tv_bits:
        lines += ["---", "### 🏢 أساسيات TradingView (فورية)"]
        lines += [f"- {b}" for b in tv_bits]
    lines += ["---", "**الأسباب:**"]
    lines += [f"- {x}" for x in r["reasons"]]

    lines += _esthmr_report_sections(r)

    lines += ["---", "### 🕵️ فحص البيانات"]
    lines.append(f"**آخر إغلاق → الآن:** {r['closes_line']}")
    lines.append("- ✅ الأسعار والمؤشرات من TradingView مباشرة — مصدر واحد موثوق بدون تحويل")

    lines += ["---", "⚠️ *تحليل تعليمي — مش نصيحة مالية*"]
    return "\n".join(lines)


# ============ قايمتك ⭐ ============

DEFAULT_WATCHLIST = ["COMI", "ABUK", "TMGH", "SWDY", "HRHO", "ETEL",
                     "EAST", "ORHD", "ADIB", "KIMA", "EFID", "PHDC"]

WATCH_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "watchlist.json")


def load_watchlist():
    try:
        with open(WATCH_FILE) as f:
            wl = json.load(f)
        if isinstance(wl, list) and wl:
            return [str(s).strip().upper() for s in wl]
    except Exception:
        pass
    return DEFAULT_WATCHLIST.copy()


def save_watchlist(wl):
    wl = sorted(set(str(s).strip().upper() for s in wl if str(s).strip()))
    try:
        with open(WATCH_FILE, "w") as f:
            json.dump(wl, f)
    except Exception:
        pass
    return wl


# ============ قايمة بديلة + سكرينر esthmr (فقط لو TradingView وقع) ============

FALLBACK_STOCKS = ["COMI", "ABUK", "HRHO", "ETEL", "TMGH", "SWDY",
                   "EAST", "ORHD", "ADIB", "KIMA", "EFID", "PHDC",
                   "AMOC", "SKPC", "SUGR", "ECRC", "CIRA", "CLHO",
                   "EGAL", "ISPH", "OKBA", "TALG"]


def fetch_all_symbols():
    global ALL_STOCKS
    try:
        df = tv_market_df()
        if df is not None and not df.empty:
            syms = sorted(s for s in df["sym"].unique() if str(s).isalnum())
            if len(syms) > 20:
                ALL_STOCKS = syms
    except Exception:
        pass
    if ALL_STOCKS:
        return ALL_STOCKS
    return sorted(set(DEFAULT_WATCHLIST + FALLBACK_STOCKS))


def esthmr_scan(min_liq_millions, limit=50):
    """سكرينر esthmr الرسمي — يُستخدم فقط لو TradingView مش متاح.
    بترجّع (DataFrame, total) أو (None, None)."""
    if not HAS_ESTHMR:
        return None, None
    try:
        txt = ec.screen(traded_value_min=int(min_liq_millions * 1e6),
                        limit=limit, sort_by="traded_value", order="desc")
        rows, total = ec.parse_screen(txt)
    except Exception:
        return None, None
    if not rows:
        return None, None
    df = pd.DataFrame(rows)
    for c in ["sym", "traded_value", "market_cap"]:
        if c not in df.columns:
            df[c] = None
    return df[["sym", "traded_value", "market_cap"]], total


# ============ الواجهة ============

if "watchlist" not in st.session_state:
    st.session_state.watchlist = load_watchlist()
if "all_stocks" not in st.session_state:
    st.session_state.all_stocks = fetch_all_symbols()

st.title("📈 محلل البورصة المصرية — EGX-Pro")
st.caption("السوق كله لحظياً من TradingView في طلب واحد + شارت TradingView مدمج "
           "+ طبقة رسمية من esthmr.com (مطلعين، إفصاحات، أساسيات) — بدون أي اعتماد على Yahoo")
if HAS_ESTHMR:
    st.caption("🔋 " + ec.status_line())
else:
    st.caption("⚪ طبقة esthmr مش مفعلة — حط esthmr_client.py جنب التطبيق")

tab1, tab2, tab3, tab4 = st.tabs(["🕵️ مسح السوق", "🔍 تحليل سهم واحد",
                                  "⭐ قايمتي", "🌐 نظرة السوق"])

# ---------- تاب المسح ----------
with tab1:
    c1, c2, c3 = st.columns(3)
    scope = c1.selectbox("النطاق", ["كل السوق", "⭐ قايمتي"])
    min_liq = c2.slider("أقل سيولة يومية (مليون ج)", 1, 50, 5)
    top_n = c3.slider("عدد الأسهم المعروضة", 5, 50, 15)

    with st.expander("🧮 يعني إيه الدرج؟ (نظام التقييم)"):
        st.markdown(
            "الدرج مجموع نقاط إشارات فنية — كل الإشارات من بيانات TradingView "
            "وإشارة المطلعين من esthmr:\n"
            "- ✅ **+2** RSI تحت 30 (تشبع بيعي) — والعكس **−2** لو فوق 70 (تشبع شرائي)\n"
            "- ✅ **+2** تقاطع MACD صاعد جديد (إغلاق أمس كان تحت خط الإشارة واليوم فوقه)\n"
            "- ✅ **+1** السعر فوق SMA50 وSMA50 فوق SMA200 (اتجاه صاعد) — والعكس **−1**\n"
            "- ✅ **+2** السعر ملاصق لدعم فني قوي (في حدود 2% منه)\n"
            "- ✅ **+1** ارتداد من البولينجر السفلي\n"
            "- 🕵️ **±** إشارة تعاملات المطلعين من esthmr (شراء مطلعين موجبة)\n\n"
            "**القرار:** من +4 وأكثر → 🟢 شراء | من +2 لـ +3 → 🟡 شراء محتمل | "
            "من −2 وأقل → 🔴 بيع / ابتعاد | بينهم → ⚪ محايد — استنى")

    if st.button("🚀 ابدأ المسح", type="primary"):
        status_ph = st.empty()
        table_ph = st.empty()
        summary_ph = st.empty()
        try:
            warn = ""
            if scope == "كل السوق":
                with st.spinner("⏳ عم نجيب السوق كله (296 سهم) من TradingView في طلب واحد..."):
                    scan_df = tv_market_df(force=True)
                if scan_df is None or scan_df.empty:
                    est_df, est_total = esthmr_scan(min_liq)
                    if est_df is not None and not est_df.empty:
                        status_ph.markdown(
                            "⚠️ TradingView مش متاح دلوقتي — دي أعلى السيولة من "
                            "سكرينر esthmr الرسمي (التحليل الفني يحتاج TradingView)")
                        est_df["traded_value"] = pd.to_numeric(
                            est_df["traded_value"], errors="coerce")
                        est_df = est_df.sort_values("traded_value", ascending=False)
                        table_ph.dataframe(est_df, use_container_width=True,
                                           hide_index=True)
                        st.stop()
            else:
                wl = st.session_state.watchlist
                if not wl:
                    st.warning("⚪ قايمتك فاضية — ضيف أسهم من تاب ⭐ قايمتي")
                    st.stop()
                mkt = tv_market_df(force=True)
                scan_df = mkt[mkt["sym"].isin(wl)].copy() \
                    if mkt is not None and not mkt.empty else pd.DataFrame()
                have = set(scan_df["sym"]) if not scan_df.empty else set()
                missing = [s for s in wl if s not in have]
                if missing:
                    with st.spinner(f"⏳ عم نجيب {len(missing)} سهم مباشرة..."):
                        try:
                            dfx = _tv_scan(TV_COLUMNS,
                                           tickers=[f"EGX:{s}" for s in missing],
                                           sort_by="volume", limit=60)
                            dfx = _clean_market_df(dfx)
                            scan_df = pd.concat([scan_df, dfx], ignore_index=True) \
                                if not scan_df.empty else dfx
                        except Exception:
                            pass

            if scan_df is None or scan_df.empty:
                status_ph.error("❌ فشل المسح — TradingView ممكن يكون مقفل مؤقتاً، جرب تاني")
                st.stop()

            n_all = len(scan_df)
            scan_df = scan_df.copy()
            scan_df["avg_value"] = scan_df["close"].fillna(0) * scan_df["avg_vol30"].fillna(0)
            scan_df["today_value"] = scan_df["close"].fillna(0) * scan_df["vol"].fillna(0)
            scan_df["rank_val"] = scan_df[["avg_value", "today_value"]].max(axis=1)
            scan_df = scan_df[(scan_df["close"] > 0) &
                              (scan_df["rank_val"] >= min_liq * 1e6)]
            scan_df = scan_df.sort_values("rank_val", ascending=False)
            if scope == "كل السوق":
                scan_df = scan_df.head(top_n)
            scan_df = scan_df.reset_index(drop=True)

            if scan_df.empty:
                status_ph.warning("⚪ مفيش أسهم فوق حد السيولة ده — قلل الحد")
                st.stop()

            # التحليل محلي بالكامل — لحظي بدون أي طلبات إضافية
            rows, skipped = [], 0
            for rec in scan_df.to_dict("records"):
                sym = str(rec.get("sym", "")).upper()
                v = v_from_record(rec)
                row = deep_row_tv(sym, v)
                if row is None:
                    skipped += 1
                else:
                    rows.append(row)

            if not rows:
                status_ph.error("❌ مفيش سهم اتحلل — جرب تاني")
                st.stop()

            res = pd.DataFrame(rows)
            status_ph.markdown(
                f"{warn}✅ **خلص المسح** — السوق: {n_all} سهم | "
                f"فوق فلتر السيولة: {len(scan_df)} | اتحلل: {len(rows)} "
                f"(اتخطى {skipped}) | ⏰ {now_cairo().strftime('%H:%M')} "
                f"— *المصدر: TradingView*")
            table_ph.dataframe(build_table(res),
                               use_container_width=True, hide_index=True)

            alive = res[res["d"].notna()] if "d" in res.columns else res
            nbuy = int((alive["score"] >= 4).sum())
            nmid = int(((alive["score"] >= 2) & (alive["score"] < 4)).sum())
            nsell = int((alive["score"] <= -2).sum())
            nneu = len(alive) - nbuy - nmid - nsell

            picks = alive[alive["score"] >= 2].sort_values("score", ascending=False).head(3)
            if len(picks):
                plines = ["", "**🎯 أعلى الفرص:**"]
                for i2, r2 in enumerate(picks.itertuples(), 1):
                    d2 = r2.d
                    ins_line = ""
                    if HAS_ESTHMR and ec.can_request(r2.sym):
                        try:
                            pest = ec.parse_snapshot(ec.snapshot(r2.sym))
                            sig, why = ec.insider_signal(pest)
                            if why:
                                ins_line = f" | {why.split('—')[0].strip()}"
                        except Exception:
                            pass
                    plines.append(
                        f"{i2}. **{r2.sym}** — {r2.dec} | دخول {d2['entry'][0]}–{d2['entry'][1]}"
                        f" | وقف {d2['stop_loss']} | هدف {d2['resistance']} | R/R {d2['rr']}"
                        f"{ins_line}")
            else:
                plines = ["", "**🎯 أعلى الفرص:** مفيش حاجة واضحة دلوقتي — الصبر أحسن"]

            summary_ph.markdown(
                "### 📋 الملخص\n"
                f"🟢 شراء: **{nbuy}** | 🟡 شراء محتمل: **{nmid}** | "
                f"⚪ محايد: **{nneu}** | 🔴 بيع: **{nsell}**\n"
                + "\n".join(plines)
                + "\n\n⚠️ *تحليل تعليمي — مش نصيحة مالية*")
        except Exception as e:
            status_ph.error(f"❌ حصلت مشكلة في المسح: {e}")

# ---------- تاب التحليل الفردي ----------
with tab2:
    syms = st.session_state.all_stocks
    if not syms:
        st.warning("مفيش قايمة أسهم — دوس حدّث")
    else:
        rc1, rc2 = st.columns([3, 1])
        idx = syms.index("COMI") if "COMI" in syms else 0
        sym_sel = rc1.selectbox(f"اختار السهم — {len(syms)} سهم متاح",
                                syms, index=idx)
        sym_manual = rc2.text_input("أو اكتب رمز يدوي", placeholder="اختياري")
        b1, b2 = st.columns([1, 3])
        if b1.button("🔄 حدّث القايمة"):
            st.session_state.all_stocks = fetch_all_symbols()
            st.rerun()
        if b2.button("🔍 حلّل", type="primary"):
            symbol = (sym_manual or sym_sel).strip().upper()
            if not symbol:
                st.warning("اكتب رمز السهم الأول")
            else:
                with st.spinner(f"عم نحلل {symbol} من TradingView..."):
                    try:
                        r = analyze(symbol)
                        st.markdown(report(r))
                        st.markdown("### 📈 الشارت من TradingView")
                        st.caption("شارت تفاعلي حقيقي — شموع يومية + RSI، "
                                   "تقدر تغيّر الفريم وتكبّر من جواه")
                        tradingview_widget(symbol)
                    except Exception as e:
                        st.error(f"❌ حصلت مشكلة: {e}")

# ---------- تاب القايمة ----------
with tab3:
    st.markdown("قايمتك المخصوصة — بتظهر كنطاق مسح في تاب 🕵️ (اختار ⭐ قايمتي)\n\n"
                "💾 بتتحفظ طول ما التطبيق شغال")
    wl = st.session_state.watchlist
    st.info(f"القايمة فيها حالياً **{len(wl)}** سهم")
    nc1, nc2 = st.columns([3, 1])
    new_sym = nc1.text_input("ضيف سهم جديد", placeholder="مثال: ETEL")
    if nc2.button("➕ إضافة", type="primary"):
        s = new_sym.strip().upper()
        if not s:
            st.warning("اكتب الرمز الأول")
        elif s in wl:
            st.warning(f"{s} موجود في القايمة بالفعل")
        else:
            st.session_state.watchlist = save_watchlist(wl + [s])
            st.rerun()
    selected = st.multiselect("أسهم قايمتك — علّم على اللي عايز تحذفه", wl)
    dc1, dc2 = st.columns(2)
    if dc1.button("🗑️ حذف المحدد"):
        if selected:
            st.session_state.watchlist = save_watchlist(
                [x for x in wl if x not in selected])
            st.rerun()
        else:
            st.warning("علّم على الأسهم الأول")
    if dc2.button("↩️ رجّع الافتراضي"):
        st.session_state.watchlist = save_watchlist(DEFAULT_WATCHLIST)
        st.rerun()

# ---------- تاب نظرة السوق 🌐 ----------
with tab4:
    st.markdown("نظرة يومية على السوق كله من بيانات esthmr الرسمية — "
                "مؤشرات، اتساع السوق، تدفقات المستثمرين (مصريين/عرب/أجانب)، "
                "وأسهم أعلى سيولة غير عادية.")
    if not HAS_ESTHMR:
        st.warning("طبقة esthmr مش مفعلة — حط esthmr_client.py + ملفات التوكن جنب التطبيق")
    else:
        cc1, cc2 = st.columns([1, 2])
        use_cache = cc1.checkbox("استخدم كاش النهاردة (مجاني)", value=True)
        days_flow = cc2.slider("تدفقات المستثمرين — آخر كم جلسة", 1, 30, 10)
        if st.button("🌐 حدّث نظرة السوق", type="primary"):
            try:
                with st.spinner("عم نجيب نظرة السوق من esthmr..."):
                    try:
                        ov = ec.market_overview_ar() if use_cache else \
                            ec.call_tool("market_overview",
                                         {"language": "ar"}, use_cache=False)
                        st.markdown("### 📊 جلسة البورصة")
                        st.markdown(ov)
                    except ec.EsthmrQuota:
                        st.warning("🔋 خلص رصيد esthmr النهاردة — جرب بكرة")
                    except Exception as e:
                        st.error(f"❌ نظرة السوق: {e}")
                    try:
                        fl = ec.investor_flows_ar(days_flow) if use_cache else \
                            ec.call_tool("investor_flows",
                                         {"days": days_flow, "language": "ar"},
                                         use_cache=False)
                        st.markdown(f"### 💱 تدفقات المستثمرين — آخر {days_flow} جلسة")
                        st.markdown(fl)
                    except ec.EsthmrQuota:
                        pass
                    except Exception as e:
                        st.error(f"❌ التدفقات: {e}")
            finally:
                st.caption("🔋 " + ec.status_line())
