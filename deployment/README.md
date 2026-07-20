# Odoo 19 Production Deployment Paketi

Bu klasör, Windows development ortamındaki Odoo 19 custom uygulamalarını Ubuntu 24.04 tabanlı bir VPS'e güvenli ve tekrar edilebilir biçimde taşımak için hazırlanmıştır.

Bu dosyalar yalnızca şablon ve yönetim araçlarıdır. Repository oluşturulurken hiçbir VPS'e bağlanılmaz ve hiçbir production komutu otomatik çalışmaz.

## Hedef yapı

```text
/opt/odoo/odoo       Pinned Odoo 19 Community checkout
/opt/odoo/project    Custom Git repository
/opt/odoo/venv       Python 3.12 virtual environment
/etc/odoo            Gerçek, repository dışı configuration
/var/lib/odoo        data_dir ve filestore
/var/log/odoo        Odoo logları
/var/backups/odoo    Yerel backup setleri
```

## Başlamadan önce

1. [Deployment Guide](DEPLOYMENT_GUIDE.md) dosyasını baştan sona okuyun.
2. [Production Checklist](PRODUCTION_CHECKLIST.md) ile tüm güvenlik kontrollerini tamamlayın.
3. [Project Test Plan](PROJECT_TEST_PLAN.md) testlerini staging restore üzerinde uygulayın.
4. `deployment/.env.example` dosyasını VPS'te `/etc/odoo/deployment.env` olarak kopyalayıp placeholder'ları değiştirin.
5. `deployment/odoo.conf.example` dosyasını `/etc/odoo/odoo.conf` olarak kopyalayın; gerçek master password yalnızca bu korumalı dosyada bulunsun.

## Script güvenlik modeli

- `install_dependencies.sh` ve `deploy.sh`, açık `--apply` verilmeden sistem değişikliği yapmaz.
- `deploy.sh`, Odoo core'u `ODOO_COMMIT` değerine sabitler.
- `update.sh`, Odoo core'u hiçbir zaman güncellemez; yalnız custom repository'yi fast-forward eder.
- `update.sh`, varsayılan olarak önce tutarlı backup alır.
- `backup.sh`, database ve filestore için ortak timestamp/checksum/metadata üretir.
- `restore.sh`, varsayılan olarak yalnız yeni/staging DB'ye restore eder. Production cutover açık bayrak ve birebir yazılan interaktif onay ister.

Scriptler root parolası, PostgreSQL parolası veya SMTP parolası içermez. PostgreSQL bağlantısı aynı isimli Linux kullanıcısı ve DB role `odoo` üzerinden Unix socket/peer authentication kullanır.

## Kritik uyarılar

- Kaynak DB PostgreSQL 17.6'dır; hedef PostgreSQL 17.x seçimi downgrade riskini önlemek içindir. Odoo 19'un genel minimumu PostgreSQL 13'tür.
- Backup database içindeki Gmail SMTP/app password dahil uygulama secret'larını taşıyabilir.
- `/var/backups/odoo` tek başına yeterli değildir. Backup'ları şifreli off-site depoya kopyalayın ve restore testi yapın.
- `workers > 0` production modunda Nginx `/websocket` trafiğini yalnız localhost'taki `127.0.0.1:8072` portuna yönlendirir.
- Gerçek `odoo.conf`, `.env`, Certbot private key, dump ve filestore repository'ye eklenmez.
