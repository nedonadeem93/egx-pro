# -*- coding: utf-8 -*-
"""
بيطبع بلوك الـ Secrets جاهز للصق في Streamlit Cloud.

الاستخدام:
    python make_secrets.py

السكريبت بيتعار مع ملفات التوكن اللي جنب المجلد اللي هو فيه
(مثلاً انقله مؤقتاً جنب مجلد EGX-Pro المحلي أو انسخ الملفات).

⚠️ الخرج فيه بيانات حساسة — متحطوش على GitHub ولا تشاركه مع حد.
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))


def _read(name):
    try:
        with open(os.path.join(BASE, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def main():
    tok = _read("esthmr_token.json")
    creds = _read("esthmr_creds.json")
    client_id = creds.get("client_id") or tok.get("client_id") or ""
    rt = tok.get("refresh_token") or ""
    at = tok.get("access_token") or ""

    if not rt or not client_id:
        print("❌ مش لاقي refresh_token/client_id.")
        print("   شغّل السكريبت من جوه مجلد فيه esthmr_token.json و esthmr_creds.json")
        print("   (أو استخدم ملف streamlit_secrets_DO-NOT-UPLOAD.txt الجاهز).")
        sys.exit(1)

    print("# الصق ده في: share.streamlit.io → تطبيقك → Settings → Secrets")
    print()
    print("[esthmr]")
    print(f'client_id     = "{client_id}"')
    print(f'refresh_token = "{rt}"')
    if at:
        print(f'access_token  = "{at}"')
    print()
    print("# access_token اختياري — لو مش موجود التطبيق هيتجدد لوحده أول تشغيل")


if __name__ == "__main__":
    main()
