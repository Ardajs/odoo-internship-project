# Odoo 19 Production Deployment Paketi

Bu klasör, Windows development ortamındaki Odoo 19 custom uygulamalarını
Ubuntu 24.04 tabanlı VPS'e güvenli biçimde kurmak ve çalışan production
ortamını sürdürülebilir şekilde işletmek için hazırlanmıştır.

Internship Logbook production ortamı `https://stajdefterim.site` adresinde,
`odoo_production` database'iyle çalışmaktadır. Bu repository'deki dosyalar
hiçbir production komutunu kendiliğinden çalıştırmaz.

## Hedef yapı

```text
/opt/odoo/odoo       Pinned Odoo 19 Community checkout
/opt/odoo/project    Custom Git repository
/opt/odoo/venv       Python 3.12 virtual environment
/etc/odoo/odoo.conf  Gerçek Odoo configuration
/etc/odoo/odoo-ai.env Korumalı Gemini environment configuration
/var/lib/odoo        data_dir ve filestore
/var/log/odoo        Odoo logları
/var/backups/odoo    Yerel backup setleri
```

## Dokümantasyon yönlendirmesi

1. Yeni VPS, rebuild veya disaster recovery kurulumu:
   [Deployment Guide](DEPLOYMENT_GUIDE.md)
2. Günlük sağlık kontrolü, canonical update, Gemini, theme/logo, backup ve
   rollback: [Maintenance Runbook](MAINTENANCE_RUNBOOK.md)
3. Production güvenlik kontrolleri:
   [Production Checklist](PRODUCTION_CHECKLIST.md)
4. Staging ve production smoke testleri:
   [Project Test Plan](PROJECT_TEST_PLAN.md)

`deployment/.env.example` ve `deployment/odoo.conf.example` yalnız
şablondur. Gerçek `/etc/odoo/odoo.conf`, `/etc/odoo/odoo-ai.env`, rclone
config ve diğer credential dosyaları Git dışında tutulur.

## Script güvenlik modeli

- `install_dependencies.sh` ve `deploy.sh`, açık `--apply` verilmeden sistem değişikliği yapmaz.
- `deploy.sh`, Odoo core'u `ODOO_COMMIT` değerine sabitler.
- `update.sh`, Odoo core'u hiçbir zaman güncellemez; yalnız custom repository'yi fast-forward eder.
- `update.sh`, varsayılan olarak önce tutarlı backup alır.
- `backup.sh`, database ve filestore için ortak timestamp/checksum/metadata üretir.
- `offsite_backup.sh`, tamamlanmış local setleri ve SHA-256 manifestlerini
  doğrulayıp dört dosyayı korumalı rclone remote'una
  `copyto --immutable` ile kopyalar; local veya remote dosya silmez.
- `restore.sh`, varsayılan olarak yalnız yeni/staging DB'ye restore eder. Production cutover açık bayrak ve birebir yazılan interaktif onay ister.
- `migration_restore.sh`, yalnız doğrulanmış Windows `.dump` + filestore `.zip` migration setini yeni ve boş bir production hedefine restore eder; mevcut hedefleri drop veya silmez.

Scriptler root parolası, PostgreSQL parolası veya SMTP parolası içermez. PostgreSQL bağlantısı aynı isimli Linux kullanıcısı ve DB role `odoo` üzerinden Unix socket/peer authentication kullanır.

## Kritik uyarılar

- Kaynak DB PostgreSQL 17.6'dır; hedef PostgreSQL 17.x seçimi downgrade riskini önlemek içindir. Odoo 19'un genel minimumu PostgreSQL 13'tür.
- Backup database içindeki Gmail SMTP/app password dahil uygulama secret'larını taşıyabilir.
- `/var/backups/odoo` tek başına yeterli değildir. Backup'ları şifreli off-site depoya kopyalayın ve restore testi yapın.
- Local backup ve off-site upload ayrı systemd service/timer birimleridir.
  Remote veya ağ kesintisi local backup sonucunu değiştirmez; off-site hata
  ayrıca izlenmelidir.
- Rclone OAuth config yalnız `/etc/rclone/odoo-rclone.conf` altında `root:root 0600` tutulur. Config içeriği, token veya client secret Git'e ya da dokümantasyona yazılmaz.
- Gemini production config'i `/etc/odoo/odoo-ai.env` üzerinden yalnız Odoo
  server process'ine verilir. Production'da `mock` provider kullanılmaz.
- `workers > 0` production modunda Nginx `/websocket` trafiğini yalnız localhost'taki `127.0.0.1:8072` portuna yönlendirir.
- Gerçek `odoo.conf`, `odoo-ai.env`, `.env`, API key, OAuth token, Certbot
  private key, dump ve filestore repository'ye eklenmez.
