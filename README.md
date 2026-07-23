# Odoo 19 Custom Applications

Bu repository, Windows üzerinde geliştirilen Odoo 19 custom uygulamalarını ve
Ubuntu Linux production işletim dokümantasyonunu içerir. Internship Logbook
uygulaması `https://stajdefterim.site` adresinde production ortamında
çalışmaktadır.

## Custom modüller

- `dev_addons/ardaapp`
- `dev_addonsI/internship_logbook`
- `dev_addonsI/sales_app`
- `custom_addons/course_student_management`

`internship_logbook` modülü; stajyer, staj programı, günlük staj kaydı,
onay/revizyon akışı, e-posta bildirimi, QWeb PDF raporu ve Gemini tabanlı AI
Writing Assistant özelliklerini içerir. Production'da doğrulanmış custom
uygulama modülü `internship_logbook`'tur.

## Ortamlar

- Development: Windows, `odoo_test`, yerel PostgreSQL ve Windows'a özel Python virtual environment
- Production: Ubuntu Linux, `odoo_production`, PostgreSQL, `odoo.service`,
  Nginx ve HTTPS

Windows `.venv` klasörü production sunucuya kopyalanmaz. Ubuntu üzerinde Python 3.12 ile yeni bir virtual environment oluşturulur.

## Odoo core ayrımı

Odoo Community core bu repository'ye dahil edilmez. Production sunucuda ayrı olarak klonlanır ve test edilmiş bir commit SHA'ya sabitlenir:

```text
/opt/odoo/odoo       Odoo 19 Community core
/opt/odoo/project    Bu custom repository
/opt/odoo/venv       Linux Python virtual environment
```

Odoo core güncellemeleri ile custom proje güncellemeleri birbirinden bağımsızdır. Custom `update.sh`, Odoo core'u otomatik güncellemez.

## Deployment

Dokümantasyon:

- Yeni sunucu/rebuild: [Deployment Guide](deployment/DEPLOYMENT_GUIDE.md)
- Günlük bakım, güncelleme ve rollback:
  [Maintenance Runbook](deployment/MAINTENANCE_RUNBOOK.md)
- Güvenlik ve production kontrolleri:
  [Production Checklist](deployment/PRODUCTION_CHECKLIST.md)
- Fonksiyonel doğrulama: [Project Test Plan](deployment/PROJECT_TEST_PLAN.md)

Repository'ye gerçek `odoo.conf`, `odoo-ai.env`, `.env`, database dump,
filestore, SMTP parolası, Gemini API key, OAuth token, private key veya başka
bir secret commit etmeyin.
