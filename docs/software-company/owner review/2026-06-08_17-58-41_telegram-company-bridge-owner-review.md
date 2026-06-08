# Telegram Company Bridge - Owner Review

Generated: 2026-06-08 17:58

## Summary

تم تجهيز أول طبقة عملية لربط شركة السوفتوير مع Telegram.

## What Changed

- تمت إضافة سكربت `scripts/software_company/telegram_bridge.py`.
- السكربت يقرأ أسرار Telegram من environment variables فقط، ولا يحفظ التوكن داخل الكود.
- تمت إضافة أمر لاستخراج `chat_id` و `message_thread_id` من Telegram updates.
- تمت إضافة أمر لإرسال رسالة إلى topic محدد.
- تمت إضافة أمر لإرسال آخر owner review إلى Topic المالك.
- تمت إضافة اختبارات تغطي استخراج الـ topics وربط أسماء الأقسام بمتغيرات البيئة.
- تم تحديث `docs/software-company/README.md` بتعليمات Telegram.

## Current Blocker

Telegram لم يرجع updates بعد. السبب المرجح أن Bot Privacy Mode مفعل، لذلك البوت لا يرى الرسائل العادية داخل الجروب.

## Owner Action Needed

أرسل أمر واحد داخل كل Topic حتى يظهر في `getUpdates`:

```txt
/topic_owner_review
/topic_pm
/topic_product
/topic_architecture
/topic_design
/topic_developers_manager
/topic_developers
/topic_qa
/topic_devops
/topic_incidents
```

بعدها يتم تشغيل:

```sh
python3 scripts/software_company/telegram_bridge.py updates
```

## Verification

```txt
tests/test_telegram_bridge.py: 3 passed
```

## Security Note

التوكن الذي أرسله المالك في المحادثة يجب اعتباره مؤقتا. بعد اكتمال الربط، يفضل توليد توكن جديد من BotFather وحفظه فقط في `api/.env` و Railway Variables.
