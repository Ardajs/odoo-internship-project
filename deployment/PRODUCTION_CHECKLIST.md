# Odoo 19 Production Checklist

Bu checklist hem ilk kurulum/rebuild kabulü hem de periyodik production
kontrolü içindir. Günlük operasyon komutları için
[MAINTENANCE_RUNBOOK.md](MAINTENANCE_RUNBOOK.md) kullanılmalıdır.

## Doğrulanmış mevcut production durumu

- [x] Domain `stajdefterim.site` HTTPS üzerinden erişilebilir.
- [x] HTTP, HTTPS'e yönleniyor.
- [x] HTTPS isteği Odoo `/odoo` yönlendirmesi döndürüyor.
- [x] Production database `odoo_production`.
- [x] Odoo 19 Community systemd servisi `odoo.service`.
- [x] `postgresql` enabled ve active.
- [x] `odoo` enabled ve active.
- [x] `nginx` enabled ve active.
- [x] `odoo-backup.timer` enabled ve active.
- [x] `odoo-offsite-backup.timer` enabled ve active.
- [x] `certbot.timer` enabled ve active.
- [x] Gemini AI Writing Assistant production'da çalışıyor.

## Git ve kaynak kod

- [ ] Custom Git repository yalnız `dev_addons`, `dev_addonsI`, `custom_addons`, `deployment` ve proje metadata dosyalarını içeriyor.
- [ ] Upstream `addons/`, `odoo/`, `odoo-bin` ve upstream test/private-key fixture'ları custom repository'de yok.
- [ ] `.venv`, `venv`, `__pycache__` ve `.pyc` Git'te yok.
- [ ] `odoo.conf`, `odoo.conf.txt`, `.env`, dump, ZIP ve filestore Git'te yok.
- [ ] İlk push öncesinde staged diff ve secret taraması yapıldı.
- [ ] Odoo core branch'i `19.0` ve checkout test edilmiş `ODOO_COMMIT` SHA'sında.
- [ ] Custom repository çalışma ağacı temiz ve production commit'i kaydedildi.

## PostgreSQL

- [ ] PostgreSQL 17.x kurulu ve çalışıyor.
- [ ] Kaynak PostgreSQL 17.6'dan daha eski bir major sürüme restore yapılmıyor.
- [ ] PostgreSQL role `odoo` mevcut; superuser değil.
- [ ] Production database `odoo_production` mevcut ve owner/restore role doğru.
- [ ] Odoo Unix socket üzerinden PostgreSQL'e bağlanıyor.
- [ ] PostgreSQL public interface üzerinde dinlemiyor.
- [ ] 5432 UFW/public güvenlik grubunda açık değil.
- [ ] Staging restore provası başarıyla tamamlandı.
- [ ] Restore sonrasında `ANALYZE` çalıştırıldı.

## Database ve filestore

- [ ] Database dump ve filestore arşivinin timestamp'i eşleşiyor.
- [ ] SHA-256 checksum doğrulandı.
- [ ] Windows migration backup SHA-256 değerleri `checksums.txt` ile doğrulandı.
- [ ] Windows migration dump catalog'u `pg_restore --list` ile okunabiliyor.
- [ ] Windows migration ZIP integrity kontrolü `unzip -t` ile başarılı.
- [ ] Target database restore öncesinde mevcut değildi.
- [ ] Target filestore restore öncesinde mevcut değildi.
- [ ] PostgreSQL restore sırasında `--no-owner` kullanıldı.
- [ ] PostgreSQL restore sırasında `--no-privileges` kullanıldı.
- [ ] Filestore klasör adı production database adıyla birebir eşleşiyor.
- [ ] Filestore owner `odoo:odoo`.
- [ ] DB attachment referansları ve fiziksel dosyalar örneklemle doğrulandı.
- [ ] Backup metadata Odoo/PostgreSQL/custom commit bilgilerini içeriyor.
- [ ] Backup restore testi yapıldı.
- [ ] En az 7 günlük local retention yapılandırıldı.
- [ ] Erişim kontrollü off-site backup mevcut; client-side encryption kullanılıp kullanılmadığı açıkça kayıtlı.
- [ ] Off-site backup'tan restore testi planlandı veya tamamlandı.
- [ ] Rclone config `/etc/rclone/odoo-rclone.conf` altında ve Git repository dışında.
- [ ] Rclone config owner/mode değeri `root:root 0600`.
- [ ] OAuth token veya rclone config içeriği dokümantasyona, loglara ya da Git'e yazılmadı.
- [ ] Root kullanıcısı korumalı config ile yapılandırılmış rclone remote'unu görebiliyor.
- [ ] Manuel `offsite_backup.sh` testi başarılı.
- [ ] Remote backup setinde `.dump`, `.tar.gz`, `.metadata` ve `.sha256` dosyaları mevcut.
- [ ] Local ve remote set `rclone check --one-way` ile doğrulandı.
- [ ] Off-site script `sync`, `move`, `delete` veya `purge` kullanmıyor.
- [ ] `odoo-offsite-backup.service` manuel çalıştırma testi başarılı.
- [ ] `odoo-offsite-backup.timer` enabled ve `Persistent=true`.
- [ ] Local ve off-site timer'ların birbirinden bağımsız olduğu doğrulandı.
- [ ] Off-site hata inceleme prosedürü `journalctl` ile test edildi.
- [ ] Remote/ağ kesintisinin tamamlanmış local backup setini etkilemediği doğrulandı.
- [ ] Local backup restore testi tamamlandı.
- [ ] Off-site remote'dan indirilen backup ile staging restore testi planlandı veya tamamlandı.

## Odoo configuration ve service

- [ ] Gerçek config `/etc/odoo/odoo.conf` altında.
- [ ] Config owner `root:odoo`, mode `0640`.
- [ ] `admin_passwd` güçlü ve development değerinden farklı.
- [ ] PostgreSQL credential rotate edildi; socket/peer kullanılıyorsa config'de parola yok.
- [ ] `proxy_mode=True`.
- [ ] `list_db=False`.
- [ ] `db_name` ve `dbfilter` yalnız production DB ile eşleşiyor.
- [ ] `http_interface=127.0.0.1`.
- [ ] HTTP port `8069` yalnız localhost'ta.
- [ ] Gevent/websocket port `8072` yalnız localhost'ta.
- [ ] `workers > 0` ve değer VPS CPU/RAM ölçümüne göre belirlendi.
- [ ] `max_cron_threads` VPS kapasitesine göre belirlendi ve en az bir mail/cron worker var.
- [ ] Memory ve time limitleri ölçüm/kapasite planına göre belirlendi.
- [ ] Odoo service root olarak çalışmıyor; `User=odoo`, `Group=odoo`.
- [ ] `systemctl is-enabled odoo` başarılı.
- [ ] `systemctl is-active odoo` başarılı.
- [ ] Odoo restart/reboot sonrası otomatik başladı.
- [ ] `/var/log/odoo/odoo.log` yazılıyor ve logrotate testi yapıldı.

## Nginx, DNS, HTTPS ve firewall

- [ ] `stajdefterim.site` doğru public IP'ye çözülüyor.
- [ ] Nginx config'de placeholder kalmadı.
- [ ] `/` istekleri `127.0.0.1:8069` adresine gidiyor.
- [ ] `/websocket` istekleri `127.0.0.1:8072` adresine gidiyor.
- [ ] Host, X-Real-IP, X-Forwarded-For ve X-Forwarded-Proto header'ları mevcut.
- [ ] Websocket Upgrade/Connection header'ları mevcut.
- [ ] `nginx -t` başarılı.
- [ ] HTTPS sertifikası geçerli.
- [ ] HTTP otomatik olarak HTTPS'e yönleniyor.
- [ ] `certbot renew --dry-run` başarılı.
- [ ] Certbot auto-renew timer aktif.
- [ ] Gerçek `SSH_PORT`, UFW enable öncesinde ikinci bir SSH terminalinden test edildi.
- [ ] SSH allow kuralı `ufw status numbered` çıktısında doğrulandı.
- [ ] UFW yalnız SSH, HTTP ve HTTPS'e izin veriyor.
- [ ] 8069 public değil.
- [ ] 8072 public değil.
- [ ] 5432 public değil.

## Secret ve e-posta

- [ ] Odoo master password rotate edildi.
- [ ] Development PostgreSQL parolası production'da kullanılmıyor.
- [ ] Gmail SMTP/app password rotate edildi.
- [ ] SMTP sender/domain ayarları doğrulandı.
- [ ] Backup'ların SMTP credential içerebildiği erişim politikasında belirtildi.
- [ ] Test e-postası başarıyla gönderildi.
- [ ] Mail queue işlendi ve hata kuyruğu kontrol edildi.
- [ ] Scheduled Actions/cron çalışıyor.

## Gemini AI

- [ ] Systemd drop-in `/etc/systemd/system/odoo.service.d/ai.conf` mevcut.
- [ ] Drop-in `EnvironmentFile=/etc/odoo/odoo-ai.env` kullanıyor.
- [ ] `/etc/odoo/odoo-ai.env` Git dışında, restrictive owner/mode ile korunuyor.
- [ ] `INTERNSHIP_AI_ENABLED` production'da aktif.
- [ ] `INTERNSHIP_AI_PROVIDER=gemini`; production'da `mock` kullanılmıyor.
- [ ] API key yalnız server-side environment üzerinden Odoo process'ine veriliyor.
- [ ] API key değeri diagnostic çıktısında, logda veya dokümantasyonda görünmüyor.
- [ ] API key yalnız mevcut/yok şeklinde güvenli yöntemle doğrulandı.
- [ ] Intern kendi draft/revision entry'sinde AI kullanabiliyor.
- [ ] Supervisor AI kullanamıyor.
- [ ] Submitted/Approved apply backend tarafından reddediliyor.
- [ ] Suggestions ve Missing Details business field değiştirmiyor.
- [ ] Gemini quota, billing ve maliyet takibi için sorumlu/uyarı tanımlı.

## Uygulama testleri

- [ ] Production database için Odoo 19 registry testi başarılı.
- [ ] Attachment karşılaştırmasında missing physical file sayısı `0`.
- [ ] Admin login testi başarılı.
- [ ] Intern login ve record-rule testi başarılı.
- [ ] Supervisor login ve record-rule testi başarılı.
- [ ] Manager yetki testi başarılı.
- [ ] `internship.student` CRUD/yetki testleri tamamlandı.
- [ ] `internship.program` oluşturma, başlatma ve tamamlama akışı test edildi.
- [ ] `internship.daily.entry` oluşturma ve güncelleme test edildi.
- [ ] Submit akışı test edildi.
- [ ] Approve akışı test edildi.
- [ ] Revision Request ve tekrar submit akışı test edildi.
- [ ] PDF oluşturuldu ve layout kontrol edildi.
- [ ] PDF'deki yinelenen “Approved Daily Entries” satırı için karar verildi.
- [ ] Company logo'nun PDF'de gösterilip gösterilmeyeceğine karar verildi.
- [ ] Attachment upload/download testi başarılı.
- [ ] Internship application icon
  `dev_addonsI/internship_logbook/static/src/img/internship.png` yükleniyor.
- [ ] Kurulu MuK theme/support modülleri açılıyor ve asset hatası yok.

## Routine maintenance

- [ ] Odoo/PostgreSQL/Nginx health kontrolü yapıldı.
- [ ] HTTPS ve `certbot.timer` kontrol edildi.
- [ ] Son local backup ve SHA-256 sonucu doğrulandı.
- [ ] Son off-site backup logu başarılı.
- [ ] Disk, inode, RAM ve swap kullanımı kontrol edildi.
- [ ] Production Git branch `main` ve working tree temiz.
- [ ] Son Odoo error logları incelendi.
- [ ] Periyodik restore provası yapıldı veya takvimi güncel.

## Initial cutover/rebuild ve rollback

- [ ] Cutover bakım penceresi duyuruldu.
- [ ] Windows Odoo'da yazma işlemleri durduruldu.
- [ ] Final eşlenmiş DB+filestore backup alındı ve checksum doğrulandı.
- [ ] Final backup off-site konuma da kopyalandı.
- [ ] Production restore tamamlandı.
- [ ] Custom modül upgrade komutu başarıyla tamamlandı.
- [ ] Login, CRUD, mail, PDF ve attachment smoke testleri tamamlandı.
- [ ] Eski DB/filestore veya doğrulanmış backup rollback için korunuyor.
- [ ] Rollback sorumlusu ve karar süresi belirlendi.
