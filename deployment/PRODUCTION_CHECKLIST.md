# Odoo 19 Production Checklist

Her madde kanıtla doğrulanmadan production cutover tamamlanmış sayılmaz.

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
- [ ] Production database `DATABASE_NAME` mevcut ve owner/restore role doğru.
- [ ] Odoo Unix socket üzerinden PostgreSQL'e bağlanıyor.
- [ ] PostgreSQL public interface üzerinde dinlemiyor.
- [ ] 5432 UFW/public güvenlik grubunda açık değil.
- [ ] Staging restore provası başarıyla tamamlandı.
- [ ] Restore sonrasında `ANALYZE` çalıştırıldı.

## Database ve filestore

- [ ] Database dump ve filestore arşivinin timestamp'i eşleşiyor.
- [ ] SHA-256 checksum doğrulandı.
- [ ] Filestore klasör adı production database adıyla birebir eşleşiyor.
- [ ] Filestore owner `odoo:odoo`.
- [ ] DB attachment referansları ve fiziksel dosyalar örneklemle doğrulandı.
- [ ] Backup metadata Odoo/PostgreSQL/custom commit bilgilerini içeriyor.
- [ ] Backup restore testi yapıldı.
- [ ] En az 7 günlük local retention yapılandırıldı.
- [ ] Şifreli off-site backup mevcut.
- [ ] Off-site backup'tan restore testi planlandı veya tamamlandı.

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

- [ ] `DOMAIN_NAME` doğru public IP'ye çözülüyor.
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

## Uygulama testleri

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
- [ ] `ardaapp` temel CRUD testi başarılı.
- [ ] `sales_app` ürün/sequence/order testi başarılı.
- [ ] `course_student_management` course/session/student testi başarılı.

## Cutover ve rollback

- [ ] Cutover bakım penceresi duyuruldu.
- [ ] Windows Odoo'da yazma işlemleri durduruldu.
- [ ] Final eşlenmiş DB+filestore backup alındı ve checksum doğrulandı.
- [ ] Final backup off-site konuma da kopyalandı.
- [ ] Production restore tamamlandı.
- [ ] Custom modül upgrade komutu başarıyla tamamlandı.
- [ ] Login, CRUD, mail, PDF ve attachment smoke testleri tamamlandı.
- [ ] Eski DB/filestore veya doğrulanmış backup rollback için korunuyor.
- [ ] Rollback sorumlusu ve karar süresi belirlendi.
