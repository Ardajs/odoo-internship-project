# Odoo 19 Custom Applications

Bu repository, Windows üzerinde geliştirilen ve Ubuntu Linux üzerinde production ortamında çalıştırılması planlanan Odoo 19 custom uygulamalarını içerir.

## Custom modüller

- `dev_addons/ardaapp`
- `dev_addonsI/internship_logbook`
- `dev_addonsI/sales_app`
- `custom_addons/course_student_management`

`internship_logbook` modülü; stajyer, staj programı, günlük staj kaydı, onay/revizyon akışı, e-posta bildirimi ve QWeb PDF raporu özelliklerini içerir.

## Ortamlar

- Development: Windows, `odoo_test`, yerel PostgreSQL ve Windows'a özel Python virtual environment
- Production: Ubuntu Linux, `DATABASE_NAME` (önerilen örnek: `odoo_production`), PostgreSQL 17.x, systemd, Nginx ve HTTPS

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

Production hazırlığına başlamadan önce [Türkçe deployment rehberini](deployment/DEPLOYMENT_GUIDE.md) ve [production kontrol listesini](deployment/PRODUCTION_CHECKLIST.md) okuyun.

Repository'ye gerçek `odoo.conf`, `.env`, database dump, filestore, SMTP parolası, private key veya başka bir secret commit etmeyin.
