# Windows'tan Ubuntu'ya Odoo 19 Production Deployment Rehberi

Bu rehber, mevcut Windows geliştirme ortamındaki Odoo 19 projesini database,
filestore ve custom modüllerle birlikte Ubuntu 24.04 VPS'e taşımak veya
production ortamını yeniden kurmak içindir.

Gerçek komutlara başlamadan önce tüm `SERVER_IP`, `DOMAIN_NAME`, `GITHUB_REPO_URL`, `DATABASE_NAME`, `ODOO_MASTER_PASSWORD` ve `CHANGE_ME_TO_TESTED_COMMIT_SHA` değerlerini kendi ortamınıza göre değiştirin. Secret'ları terminal history'ye veya Git repository'ye yazmayın.

> **Mevcut durum:** İlk production kurulumu tamamlanmıştır. Canlı ortam
> `https://stajdefterim.site`, database `odoo_production` ve systemd servisi
> `odoo.service` ile çalışır. Rutin health check, custom kod deployment,
> Gemini AI, MuK theme/logo, backup ve rollback işlemleri için
> [MAINTENANCE_RUNBOOK.md](MAINTENANCE_RUNBOOK.md) kullanılmalıdır. Bu
> rehberdeki migration/cutover adımlarını rutin güncelleme sırasında tekrar
> çalıştırmayın.

### Doğrulanmış canlı production özeti

```text
Domain:                 stajdefterim.site
Production database:    odoo_production
Production module:      internship_logbook
Odoo service:           odoo.service
Odoo core:              /opt/odoo/odoo
Custom repository:      /opt/odoo/project
Virtual environment:    /opt/odoo/venv
Odoo config:            /etc/odoo/odoo.conf
AI environment:         /etc/odoo/odoo-ai.env
AI systemd drop-in:      /etc/systemd/system/odoo.service.d/ai.conf
Local backup root:      /var/backups/odoo
```

## Doğrulanmış proje bilgileri

```text
Kaynak Odoo:          19.0 Community
Kaynak PostgreSQL:    17.6
Kaynak database:      odoo_test
Kaynak filestore:     %LOCALAPPDATA%\OpenERP S.A\Odoo\filestore\odoo_test
Custom modüller:      ardaapp,internship_logbook,sales_app,course_student_management
Hedef Odoo core:      /opt/odoo/odoo
Hedef custom repo:    /opt/odoo/project
Hedef virtualenv:     /opt/odoo/venv
Hedef config:         /etc/odoo/odoo.conf
Hedef data_dir:       /var/lib/odoo
```

Odoo 19 genel olarak PostgreSQL 13+ destekler. Bu proje için PostgreSQL 17.x seçilmesinin nedeni, kaynak database'in 17.6 olması ve daha eski major sürüme `pg_dump` restore'unun garanti edilmemesidir. Ayrıntı: [Odoo 19 source install](https://www.odoo.com/documentation/19.0/administration/on_premise/source.html) ve [PostgreSQL 17 pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html).

---

## 1. Git repository hazırlığı

**Nerede:** Windows, custom repository'nin bulunduğu `PROJECT_ROOT` klasörü

**Amaç:** Upstream Odoo core'u dışarıda bırakan temiz custom repository oluşturmak.

PowerShell açın:

```powershell
Set-Location -LiteralPath "PROJECT_ROOT"
git init
git status --short --ignored
```

Önce ignore kontrollerini yapın:

```powershell
git check-ignore -v odoo.conf
git check-ignore -v odoo.conf.txt
git check-ignore -v .venv
git check-ignore -v addons
git check-ignore -v odoo
git check-ignore -v deployment\.env.example
```

İlk beş hassas/upstream yol için bir ignore kuralı görünmelidir. `deployment/.env.example` için ignore çıktısı olmamalı veya son eşleşme negation kuralı olmalıdır.

Yalnız izin verilen yolları açıkça stage edin:

```powershell
git add .gitignore .gitattributes README.md LICENSE
git add dev_addons\ardaapp
git add dev_addonsI\internship_logbook
git add dev_addonsI\sales_app
git add custom_addons\course_student_management
git add deployment
git status --short
```

**Beklenen sonuç:** `addons/`, `odoo/`, `.venv/`, `odoo.conf`, `odoo.conf.txt`, dump ve filestore staged listede yer almaz.

## 2. GitHub push öncesi secret kontrolü

**Nerede:** Windows proje kökü

**Amaç:** İlk commit'e gerçek credential veya backup girmediğini doğrulamak.

```powershell
git diff --cached --name-only
git diff --cached --stat
git diff --cached
```

Şüpheli dosya adlarını kontrol edin:

```powershell
git diff --cached --name-only | Select-String -Pattern 'odoo\.conf\.txt|\.env$|\.dump$|\.sql$|\.zip$|filestore|\.pem$|\.key$'
```

Placeholder dışındaki credential ifadelerini manuel inceleyin:

```powershell
git diff --cached | Select-String -Pattern 'admin_passwd|db_password|smtp_password|BEGIN PRIVATE KEY|api_key|access_token'
```

`deployment/odoo.conf.example` içindeki `ODOO_MASTER_PASSWORD` placeholder eşleşmesi beklenir; gerçek değer eşleşmesi kabul edilmez.

Kontrol temizse:

```powershell
git commit -m "Add Odoo custom modules and production deployment infrastructure"
git branch -M main
git remote add origin GITHUB_REPO_URL
git push -u origin main
```

**Beklenen sonuç:** GitHub repository yalnız custom kod ve deployment dokümantasyonunu içerir.

## 3. Database ve filestore backup

**Nerede:** Windows development makinesi

**Amaç:** Aynı cutover anına ait database ve filestore çifti oluşturmak.

### Yöntem A — Odoo Database Manager ZIP

1. Kullanıcıların development DB'ye yazmasını durdurun.
2. Odoo Database Manager ekranında `odoo_test` için ZIP backup seçin.
3. Filestore seçeneğinin dahil olduğunu doğrulayın.
4. ZIP'i repository dışında saklayın.
5. PowerShell ile checksum alın:

```powershell
Get-FileHash "BACKUP_PATH\odoo_test_backup.zip" -Algorithm SHA256
```

ZIP, database içindeki Gmail SMTP/app password dahil secret'ları taşıyabilir.

Bu tek ZIP, aşağıda açıklanan dört dosyalı Windows migration paketi değildir ve `migration_restore.sh` girdisi olarak kullanılamaz. Odoo Database Manager yöntemi seçilirse ayrı Odoo restore prosedürü uygulanmalıdır.

### Yöntem B — Doğrulanmış Windows migration paketi

Odoo terminalini/Windows servisini durdurun. Ardından PostgreSQL 17 client ile:

```powershell
pg_dump.exe -h localhost -p 5432 -U odoo18db -W -Fc -f "BACKUP_PATH\odoo_test.dump" odoo_test
```

`-W` parolayı interaktif sorar; parola komut satırına yazılmaz.

Filestore'u aynı kesinti penceresinde ZIP olarak arşivleyin. ZIP içinde `odoo_test/` üst klasörü korunmalıdır:

```powershell
Compress-Archive -LiteralPath "$env:LOCALAPPDATA\OpenERP S.A\Odoo\filestore\odoo_test" -DestinationPath "BACKUP_PATH\odoo_test_filestore.zip"
```

Bu proje için doğrulanan ve birlikte tutulması gereken set:

```text
odoo_test.dump
odoo_test_filestore.zip
checksums.txt
metadata.txt
```

`checksums.txt`, dump ve ZIP'in SHA-256 değerlerini; `metadata.txt` database adı, PostgreSQL/Odoo sürümü, backup zamanı, dosya adları ve custom modülleri içerir. Gerçek credential içermez. Dört dosyayı ayırmayın veya yeniden adlandırmayın.

**Beklenen sonuç:** Aynı cutover anına ait `.dump`, `.zip`, checksum ve metadata hazırdır. Odoo ancak iki veri dosyası tamamlandıktan sonra yeniden başlatılır.

## 4. Backup restore provası

**Nerede:** Tercihen ayrı bir Windows/staging PostgreSQL 17 ortamı

**Amaç:** VPS cutover'dan önce backup'ın gerçekten açılabildiğini doğrulamak.

```powershell
createdb.exe -h localhost -p 5432 -U odoo18db -W odoo_restore_test
pg_restore.exe -h localhost -p 5432 -U odoo18db -W --exit-on-error --no-owner --no-privileges -d odoo_restore_test BACKUP_PATH\odoo_test.dump
```

`odoo_test_filestore.zip` içindeki `odoo_test/` klasörünün içeriğini `odoo_restore_test/` adıyla ayrı data directory'ye açın. Custom addon'lar mevcutken Odoo'yu ayrı port/config ile bir defa başlatın ve login, PDF ve attachment testi yapın.

**Beklenen sonuç:** Restore hatasızdır; eski attachment açılır ve custom modüller installed görünür.

## 5. VPS hazırlığı

**Nerede:** VPS sağlayıcı paneli

**Amaç:** Ubuntu 24.04 LTS, statik public IP ve yeterli disk/RAM hazırlamak.

- Ubuntu Server 24.04 LTS seçin.
- SSH key authentication kullanın.
- Snapshot özelliğini etkinleştirin.
- Backup boyutunun birkaç katı boş disk ayırın.
- Worker sayısını belirlemeden önce CPU/RAM kapasitesini kaydedin.

**Beklenen sonuç:** `SERVER_IP` ve root olmayan sudo kullanıcısı hazırdır.

## 6. SSH bağlantısı

**Nerede:** Windows PowerShell

```powershell
ssh ubuntu@SERVER_IP
```

İlk bağlantıda host fingerprint'i VPS paneliyle doğrulayın.

**Beklenen sonuç:** Ubuntu shell prompt'u açılır.

## 7. Ubuntu update ve temel bağımlılıklar

**Nerede:** VPS SSH terminali

```bash
sudo apt update
sudo apt upgrade
sudo apt install ca-certificates curl git unzip build-essential python3.12 python3.12-venv python3.12-dev python3-pip libldap2-dev libpq-dev libsasl2-dev libxml2-dev libxslt1-dev libjpeg-dev zlib1g-dev libffi-dev libssl-dev
```

Her paket listesini onay ekranında inceleyin. Repository klonlandıktan sonra aynı kontrolü script dry-run ile yapabilirsiniz:

```bash
sudo /opt/odoo/project/deployment/scripts/install_dependencies.sh
```

Gerçek uygulama ancak açık onayla yapılır:

```bash
sudo /opt/odoo/project/deployment/scripts/install_dependencies.sh --apply
```

Script üçüncü taraf APT repository eklemez ve rastgele wkhtmltopdf binary indirmez.

**Beklenen sonuç:** Python 3.12 ve Odoo requirements'ı derlemek için sistem kütüphaneleri hazırdır.

## 8. Odoo system user ve dizinler

**Nerede:** VPS SSH terminali

```bash
sudo useradd --system --home-dir /var/lib/odoo --create-home --shell /usr/sbin/nologin --user-group odoo
sudo install -d -o root -g odoo -m 0750 /opt/odoo /etc/odoo
sudo install -d -o odoo -g odoo -m 0750 /var/lib/odoo /var/lib/odoo/filestore /var/log/odoo
sudo install -d -o root -g root -m 0700 /var/backups/odoo
id odoo
```

Kullanıcı zaten varsa `useradd` komutunu tekrar çalıştırmayın; `id odoo` ile doğrulayın.

**Beklenen sonuç:** Odoo root olmayan kilitli sistem kullanıcısıyla çalışabilir.

## 9. PostgreSQL 17.x

**Nerede:** VPS SSH terminali

Ubuntu repository'nizde `postgresql-17` bulunup bulunmadığını kontrol edin:

```bash
apt-cache policy postgresql-17
```

Paket yoksa resmi PostgreSQL PGDG repository'sini yöneticinin açık kararıyla ekleyin. Güncel talimatı önce [PostgreSQL Ubuntu download](https://www.postgresql.org/download/linux/ubuntu/) sayfasından doğrulayın:

```bash
sudo install -d -m 0755 /usr/share/postgresql-common/pgdg
sudo curl --fail --show-error --silent -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc
echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt noble-pgdg main" | sudo tee /etc/apt/sources.list.d/pgdg.list
sudo apt update
sudo apt install postgresql-17 postgresql-client-17
```

Sürümü doğrulayın:

```bash
psql --version
sudo -u postgres psql -c "SHOW server_version;"
```

Role oluşturun:

```bash
sudo -u postgres createuser --createdb --no-createrole --no-superuser odoo
```

Public TCP dinlemeyi kapatmak için:

```bash
sudoedit /etc/postgresql/17/main/postgresql.conf
```

Şu değeri ayarlayın:

```ini
listen_addresses = ''
```

`/etc/postgresql/17/main/pg_hba.conf` içinde local peer satırlarının bulunduğunu doğrulayın:

```text
local   all   postgres   peer
local   all   odoo       peer
```

Ardından:

```bash
sudo systemctl restart postgresql
sudo ss -lntp | grep 5432 || true
sudo -u odoo psql -d postgres -c "SELECT current_user, current_setting('server_version');"
```

`ss` çıktısında public `0.0.0.0:5432` veya `[::]:5432` bulunmamalı; socket bağlantısı `odoo` rolüyle başarılı olmalıdır.

## 10. Odoo 19 pinned commit

**Nerede:** VPS SSH terminali

Önce test edeceğiniz Odoo 19 commit SHA'yı belirleyin. Yalnız `19.0` branch'inin o anki HEAD'ine güvenmeyin.

```bash
sudo git clone --branch 19.0 --single-branch https://github.com/odoo/odoo.git /opt/odoo/odoo
sudo git -C /opt/odoo/odoo fetch --no-tags origin CHANGE_ME_TO_TESTED_COMMIT_SHA
sudo git -C /opt/odoo/odoo checkout --detach CHANGE_ME_TO_TESTED_COMMIT_SHA
sudo git -C /opt/odoo/odoo rev-parse HEAD
```

Çıktı, kaydettiğiniz test edilmiş SHA ile aynı olmalıdır. Bu SHA backup metadata ve change record içinde saklanır.

## 11. Python 3.12 virtual environment

**Nerede:** VPS SSH terminali

```bash
sudo python3.12 -m venv /opt/odoo/venv
sudo /opt/odoo/venv/bin/pip install setuptools wheel
sudo /opt/odoo/venv/bin/pip install -r /opt/odoo/odoo/requirements.txt
sudo /opt/odoo/venv/bin/python3 --version
```

Windows `.venv` kopyalanmaz. Custom addon'ların ek pip bağımlılığı yoktur.

`wkhtmltopdf` için:

```bash
wkhtmltopdf --version
```

Odoo 19 QWeb header/footer uyumluluğu için doğrulanmış `0.12.6` gerekir. Script rastgele binary indirmez; Ubuntu mimarinize uygun paketi resmi/denetlenmiş kaynaktan seçip staging PDF testi yapın.

## 12. Custom repository clone

**Nerede:** VPS SSH terminali

```bash
sudo git clone --branch main --single-branch GITHUB_REPO_URL /opt/odoo/project
sudo git -C /opt/odoo/project rev-parse HEAD
sudo chmod 0755 /opt/odoo/project/deployment/scripts/*.sh
```

Private repository kullanılıyorsa deploy key'i repository dışında ve minimum read yetkisiyle yapılandırın.

Addon'ları doğrulayın:

```bash
test -f /opt/odoo/project/dev_addons/ardaapp/__manifest__.py
test -f /opt/odoo/project/dev_addonsI/internship_logbook/__manifest__.py
test -f /opt/odoo/project/dev_addonsI/sales_app/__manifest__.py
test -f /opt/odoo/project/custom_addons/course_student_management/__manifest__.py
```

**Beklenen sonuç:** Dört komut da sessizce başarılı olur.

`.gitattributes` scriptlerin LF satır sonunu korur. `chmod` ise Linux executable permission'ını açıkça uygular.

## 13. Environment ve odoo.conf

**Nerede:** VPS SSH terminali

```bash
sudo cp /opt/odoo/project/deployment/.env.example /etc/odoo/deployment.env
sudo chown root:odoo /etc/odoo/deployment.env
sudo chmod 0640 /etc/odoo/deployment.env
sudoedit /etc/odoo/deployment.env
```

Tüm placeholder'ları değiştirin. Bu dosyaya master, PostgreSQL veya SMTP parolası yazmayın.

Production config:

```bash
sudo cp /opt/odoo/project/deployment/odoo.conf.example /etc/odoo/odoo.conf
sudo chown root:odoo /etc/odoo/odoo.conf
sudo chmod 0640 /etc/odoo/odoo.conf
sudoedit /etc/odoo/odoo.conf
```

`ODOO_MASTER_PASSWORD` yerine güçlü ve benzersiz master password girin. `DATABASE_NAME` değerlerini gerçek production DB adıyla değiştirin.

Placeholder kontrolü:

```bash
sudo grep -nE 'DATABASE_NAME|DOMAIN_NAME|ODOO_MASTER_PASSWORD|CHANGE_ME' /etc/odoo/odoo.conf /etc/odoo/deployment.env
```

**Beklenen sonuç:** Çıktı olmamalıdır.

Workers notu: örnek config'deki `workers=2` yalnız küçük VPS için başlangıç örneğidir. Odoo'nun önerdiği üst sınır yaklaşımı `(CPU * 2) + 1` olsa da gerçek değer RAM, eşzamanlı kullanıcı, PDF ve cron yükü ölçülerek seçilmelidir. `limit_memory_*` ve `limit_time_*` değerleri de ölçüm olmadan açılmamalıdır. [Odoo 19 production server](https://www.odoo.com/documentation/19.0/administration/on_premise/deploy.html)

Gemini AI secret'ı `odoo.conf` veya `/etc/odoo/deployment.env` içine
yazılmaz. Production'da ayrı `/etc/odoo/odoo-ai.env` dosyası kullanılır;
gerçek API key hiçbir zaman Git'e eklenmez. Ayrıntılı yapılandırma ve API
key'i yazdırmadan doğrulama komutu için
[Maintenance Runbook — Gemini](MAINTENANCE_RUNBOOK.md#5-gemini-ai-production-yapılandırması)
bölümüne bakın.

## 14. Database restore

### Windows Migration Backup Restore

**Nerede:** Önce Windows PowerShell, sonra VPS SSH terminali

Windows development ortamından doğrulanan migration seti tam olarak şu dört dosyadan oluşur:

```text
odoo_test.dump
odoo_test_filestore.zip
checksums.txt
metadata.txt
```

Bu format yalnız `migration_restore.sh` ile kullanılır. Günlük Linux backup setleri için kullanılan `restore.sh` ile karıştırılmaz.

#### 1. Geçici kullanıcı dizinine transfer

Windows PowerShell'de `SSH_PORT`, `SSH_USERNAME` ve `SERVER_IP` placeholder'larını gerçek, secret olmayan bağlantı bilgileriyle değiştirin:

Önce VPS SSH terminalinde kullanıcıya ait geçici ve kapalı dizini oluşturun:

```bash
install -d -m 0700 /home/SSH_USERNAME/odoo-migration-upload
```

Ardından Windows PowerShell'de:

```powershell
scp -P SSH_PORT "BACKUP_SOURCE_DIRECTORY\odoo_test.dump" "BACKUP_SOURCE_DIRECTORY\odoo_test_filestore.zip" "BACKUP_SOURCE_DIRECTORY\checksums.txt" "BACKUP_SOURCE_DIRECTORY\metadata.txt" SSH_USERNAME@SERVER_IP:/home/SSH_USERNAME/odoo-migration-upload/
```

**Amaç:** Dört dosyayı şifreli SSH aktarımıyla geçici kullanıcı alanına yüklemek.

**Beklenen sonuç:** Dört dosya `/home/SSH_USERNAME/odoo-migration-upload/` altında görünür. Database dump hassas SMTP ve uygulama verisi içerebilir; herkese açık veya şifresiz bir konuma yüklemeyin.

#### 2. Korumalı incoming dizinine taşıma

`TIMESTAMP` yerine cutover setini tanımlayan benzersiz zamanı yazın:

```bash
sudo install -d -o root -g root -m 0700 /var/backups/odoo/incoming/windows-cutover-TIMESTAMP
sudo mv /home/SSH_USERNAME/odoo-migration-upload/odoo_test.dump /home/SSH_USERNAME/odoo-migration-upload/odoo_test_filestore.zip /home/SSH_USERNAME/odoo-migration-upload/checksums.txt /home/SSH_USERNAME/odoo-migration-upload/metadata.txt /var/backups/odoo/incoming/windows-cutover-TIMESTAMP/
sudo chown root:root /var/backups/odoo/incoming/windows-cutover-TIMESTAMP/*
sudo chmod 0600 /var/backups/odoo/incoming/windows-cutover-TIMESTAMP/*
sudo stat -c '%U:%G %a %n' /var/backups/odoo/incoming/windows-cutover-TIMESTAMP /var/backups/odoo/incoming/windows-cutover-TIMESTAMP/*
```

**Beklenen sonuç:** Dizin `root:root 0700`, içindeki dört dosya `root:root 0600` görünür.

#### 3. Checksum, dump ve ZIP doğrulaması ile restore

Odoo production servisi henüz başlatılmamış olmalıdır. Kaynak database adı `odoo_test`, yeni production database ve filestore adı `odoo_production` olur:

```bash
sudo /opt/odoo/project/deployment/scripts/migration_restore.sh \
  --backup-dir /var/backups/odoo/incoming/windows-cutover-TIMESTAMP \
  --source-db odoo_test \
  --target-db odoo_production \
  --postgres-role odoo \
  --filestore-root /var/lib/odoo/filestore \
  --expected-file-count 474
```

Script, kullanıcıdan `MIGRATE odoo_test TO odoo_production` ifadesini aynen yazmasını ister. `474` yalnız bu doğrulanmış backup setinin beklenen sayısıdır; yeni bir final backup alınırsa güncel fiziksel dosya sayısını kullanın.

Script sırasıyla SHA-256, `pg_restore --list`, `unzip -t`, ZIP üst klasörü, hedeflerin mevcut olmaması, database restore, `ANALYZE`, modül durumları ve filestore dosya sayılarını doğrular. Restore sırasında `--no-owner --no-privileges --exit-on-error` kullanır. Mevcut bir database veya filestore'u drop/silmez.

Doğru filestore yapısı:

```text
/var/lib/odoo/filestore/odoo_production/<hash klasörleri ve dosyalar>
```

Yanlış ve kabul edilmeyen yapı:

```text
/var/lib/odoo/filestore/odoo_production/odoo_test/
```

#### 4. Registry testi

Odoo servisini başlatmadan önce:

```bash
sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin --config=/etc/odoo/odoo.conf --database=odoo_production --stop-after-init --no-http
```

Registry testi, dört custom modül ve attachment eşleşmesi doğrulandıktan sonra Odoo servisi başlatılabilir. Test başarısızsa yarım database/filestore otomatik silinmez; önce loglar ve kalan hedefler incelenir.

### Günlük Linux backup setini restore etme

`backup.sh` tarafından üretilen timestamp'li `.dump`, `.tar.gz`, `.sha256` ve `.metadata` setleri yalnız mevcut `restore.sh` ile kullanılır.

Önce staging restore:

```bash
sudo /opt/odoo/project/deployment/scripts/restore.sh --backup-dir /var/backups/odoo/BACKUP_SET_DIRECTORY --target-db odoo_restore_test
```

Production üzerinde mevcut hedefi rollback adına koruyarak restore etmek için açık onay gerekir:

```bash
sudo /opt/odoo/project/deployment/scripts/restore.sh --backup-dir /var/backups/odoo/BACKUP_SET_DIRECTORY --target-db DATABASE_NAME --production --replace-existing
```

Linux restore scripti checksum ve timestamp eşleşmesini doğrular, `--no-owner --no-privileges` kullanır, mevcut production DB/filestore'u rollback adıyla korur ve `ANALYZE` çalıştırır.

## 15. Filestore restore doğrulaması

**Nerede:** VPS SSH terminali

`restore.sh` ve `migration_restore.sh` filestore içeriğini otomatik olarak hedef DB adıyla yerleştirir. Manuel restore yapılıyorsa kaynak `odoo_test` klasörünün kendisi hedefin altına kopyalanmamalı; yalnız içeriği production DB adlı klasöre konmalıdır:

```text
/var/lib/odoo/filestore/DATABASE_NAME
```

Kontroller:

```bash
sudo find /var/lib/odoo/filestore/DATABASE_NAME -type f | wc -l
sudo du -sh /var/lib/odoo/filestore/DATABASE_NAME
sudo -u postgres psql -d DATABASE_NAME -c "SELECT count(*) AS stored_rows, count(DISTINCT store_fname) AS distinct_files FROM ir_attachment WHERE store_fname IS NOT NULL;"
```

Kaynak analizinde 474 benzersiz fiziksel filestore dosyası vardı. Final backup sonrası sayı değişebilir; DB ve filesystem değerleri final backup metadata/testiyle karşılaştırılmalıdır.

## 16. Permissions

**Nerede:** VPS SSH terminali

```bash
sudo chown -R odoo:odoo /var/lib/odoo /var/log/odoo
sudo find /var/lib/odoo -type d -exec chmod 0750 {} +
sudo find /var/lib/odoo/filestore -type f -exec chmod 0640 {} +
sudo chown root:odoo /etc/odoo/odoo.conf /etc/odoo/deployment.env
sudo chmod 0640 /etc/odoo/odoo.conf /etc/odoo/deployment.env
```

Code checkout'ları root-owned/read-only kalabilir; Odoo service yalnız okumalıdır.

## 17. systemd

**Nerede:** VPS SSH terminali

```bash
sudo cp /opt/odoo/project/deployment/odoo.service /etc/systemd/system/odoo.service
sudo install -d -o root -g root -m 0755 /etc/systemd/system/odoo.service.d
sudo systemctl daemon-reload
sudo systemctl enable odoo.service
sudo systemctl start odoo.service
sudo systemctl status odoo.service --no-pager
sudo journalctl -u odoo.service -n 100 --no-pager
```

AI environment drop-in şu içeriği taşımalıdır:

```ini
[Service]
EnvironmentFile=/etc/odoo/odoo-ai.env
```

Dosya yolu:

```text
/etc/systemd/system/odoo.service.d/ai.conf
```

`/etc/odoo/odoo-ai.env` için restrictive owner/mode kullanın ve gerçek
Gemini API key'i dokümana veya terminal çıktısına yazdırmayın. Production
provider `gemini` olmalı; `mock` kullanılmamalıdır.

Socket kontrolleri:

```bash
sudo ss -lntp | grep -E ':8069|:8072'
curl --fail http://127.0.0.1:8069/web/login -o /dev/null
curl --fail http://127.0.0.1:8072/websocket/health
```

Yalnız `127.0.0.1:8069` ve `127.0.0.1:8072` görünmelidir. 8072 yalnız `workers > 0` multiprocessing modunda websocket/gevent portudur. [Odoo 19 CLI](https://www.odoo.com/documentation/19.0/developer/reference/cli.html)

## 18. Nginx

**Nerede:** VPS SSH terminali

```bash
sudo apt install nginx
```

Sertifika henüz yokken final HTTPS config'i doğrudan etkinleştirmeyin; sertifika yolları bulunmadığı için `nginx -t` başarısız olur. Önce `/etc/nginx/sites-available/odoo-bootstrap` dosyasını oluşturun:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name DOMAIN_NAME;

    location / {
        proxy_pass http://127.0.0.1:8069;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Etkinleştirin:

```bash
sudo ln -s /etc/nginx/sites-available/odoo-bootstrap /etc/nginx/sites-enabled/odoo-bootstrap
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

**Beklenen sonuç:** Nginx HTTP üzerinden domain isteğini localhost Odoo'ya iletebilir.

## 19. DNS

**Nerede:** Domain/DNS sağlayıcı paneli

Şu kaydı oluşturun:

```text
Type: A
Name: subdomain
Value: SERVER_IP
TTL: 300 veya sağlayıcı varsayılanı
```

Kontrol:

```bash
getent ahosts DOMAIN_NAME
```

**Beklenen sonuç:** Domain VPS public IP'sine çözülür.

## 20. HTTPS ve Certbot

**Nerede:** VPS SSH terminali

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot certonly --nginx -d DOMAIN_NAME
```

Sertifika oluştuğunda final config'i kurun:

```bash
sudo cp /opt/odoo/project/deployment/nginx/odoo.conf /etc/nginx/sites-available/odoo
sudoedit /etc/nginx/sites-available/odoo
sudo rm -f /etc/nginx/sites-enabled/odoo-bootstrap
sudo ln -s /etc/nginx/sites-available/odoo /etc/nginx/sites-enabled/odoo
sudo nginx -t
sudo systemctl reload nginx
```

Final dosyada tüm `DOMAIN_NAME` placeholder'larını gerçek domain ile değiştirin.

Renewal testi:

```bash
sudo systemctl status certbot.timer --no-pager
sudo certbot renew --dry-run
```

**Beklenen sonuç:** HTTP HTTPS'e yönlenir; sertifika geçerli ve renewal testi başarılıdır.

## 21. UFW

**Nerede:** VPS SSH terminali

`SSH_PORT` yerine VPS'in gerçek SSH portunu yazın. Mevcut SSH oturumunu kapatmayın. Önce SSH ve Nginx kurallarını ekleyip kontrol edin:

```bash
sudo ufw allow SSH_PORT/tcp
sudo ufw allow 'Nginx Full'
sudo ufw status numbered
```

`SSH_PORT=22` ise `sudo ufw allow OpenSSH` profili alternatif olarak kullanılabilir. Standart dışı portta mutlaka `SSH_PORT/tcp` kuralını kullanın.

UFW henüz etkinleştirilmeden ikinci bir terminal açın ve bağlantıyı sınayın:

```bash
ssh -p SSH_PORT SSH_USERNAME@SERVER_IP
```

İkinci bağlantı başarılı olmalı ve `sudo ufw status numbered` çıktısında gerçek SSH portunun allow kuralı görünmelidir. İlk SSH oturumunu açık tutarak ancak bu iki kontrol geçtikten sonra:

```bash
sudo ufw status verbose
sudo ufw enable
sudo ufw status numbered
```

Beklenen public portlar yalnız gerçek SSH portu, 80 ve 443'tür. 5432, 8069 ve 8072 için hiçbir public allow kuralı eklemeyin.

Harici bir makineden ayrıca port scan yapın. Local `ss` çıktısı, Odoo portlarının yalnız `127.0.0.1` üzerinde olduğunu göstermelidir.

## 22. Production testleri

**Nerede:** Browser ve VPS terminali

[PROJECT_TEST_PLAN.md](PROJECT_TEST_PLAN.md) dosyasını staging'de tam olarak uygulayın. Production'da en az:

1. HTTPS login
2. Student oluşturma/okuma
3. Internship Program oluşturma
4. Daily Entry oluşturma
5. Submit
6. Revision Request
7. Tekrar submit
8. Approve
9. E-posta queue
10. PDF
11. Attachment upload/download
12. Record rule izolasyonu

smoke testlerini yapın.

Log izlemesi:

```bash
sudo journalctl -u odoo.service -f
sudo tail -f /var/log/odoo/odoo.log
sudo tail -f /var/log/nginx/odoo.error.log
```

## 23. SMTP

**Nerede:** Odoo UI

1. Development'tan gelen Gmail SMTP/app password'ü production öncesinde rotate edin.
2. Yeni credential'ı yalnız Odoo Outgoing Mail Server kaydına girin.
3. Sender address/domain uyumunu kontrol edin.
4. Connection testini çalıştırın.
5. Submit/Revision/Approve akışlarından test mail üretin.
6. Mail queue ve Scheduled Actions ekranını kontrol edin.

Gerçek SMTP password repository veya `/etc/odoo/deployment.env` içine yazılmaz. Database dump bu credential'ı içerebileceği için backup hassastır.

## 24. Backup timer

**Nerede:** VPS SSH terminali

```bash
sudo cp /opt/odoo/project/deployment/odoo-backup.service /etc/systemd/system/odoo-backup.service
sudo cp /opt/odoo/project/deployment/odoo-backup.timer /etc/systemd/system/odoo-backup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now odoo-backup.timer
sudo systemctl list-timers odoo-backup.timer
```

İlk manuel test:

```bash
sudo systemctl start odoo-backup.service
sudo systemctl status odoo-backup.service --no-pager
sudo journalctl -u odoo-backup.service -n 100 --no-pager
sudo find /var/backups/odoo -maxdepth 2 -type f -ls
```

Backup default olarak Odoo'yu kısa süre durdurur, DB dump ve filestore arşivini ortak timestamp ile üretir, checksum/metadata ekler ve servisi yeniden başlatır. Retention örneği 7 gündür.

### Rclone tabanlı off-site backup

Off-site upload, local backup'tan ayrı `odoo-offsite-backup.service` ve
`odoo-offsite-backup.timer` birimleriyle çalışır. Remote servis veya ağ hatası
off-site servisini başarısız yapar ancak daha önce tamamlanan local backup'ı
değiştirmez ve local backup service sonucuna bağlanmaz.

Script yalnız şu biçimde tamamlanmış dizinleri işler:

```text
/var/backups/odoo/odoo_production_YYYYMMDD_HHMMSS/
```

`.incomplete_*`, `.incoming_*` ve beklenen adla eşleşmeyen dizinler upload edilmez. Local SHA-256 manifest doğrulanmadan ağ işlemi başlamaz. Upload için `copyto --immutable` kullanılır; `sync`, `move`, `delete` veya `purge` kullanılmaz. Rclone'un `copyto` ve `--immutable` davranışı için [resmî rclone copyto dokümantasyonuna](https://rclone.org/commands/rclone_copyto/) bakın.

#### 1. Yetkilendirilmiş rclone config'i korumalı konuma kopyalama

**Nerede:** VPS SSH terminali

Mevcut config SSH kullanıcısı altında oluşturulduysa içeriğini ekrana
yazdırmadan kopyalayın. `SSH_USERNAME` değerini gerçek kullanıcı adıyla
değiştirin:

```bash
sudo install -d -o root -g root -m 0700 /etc/rclone
sudo install -o root -g root -m 0600 /home/SSH_USERNAME/.config/rclone/rclone.conf /etc/rclone/odoo-rclone.conf
sudo stat -c '%U:%G %a %n' /etc/rclone /etc/rclone/odoo-rclone.conf
```

**Beklenen sonuç:** `/etc/rclone` `root:root 0700`, config `root:root 0600` görünür. Google OAuth token, refresh token, client secret veya config içeriğini terminal çıktısına, Git'e, issue kaydına ya da dokümantasyona yapıştırmayın. Rclone Google Drive yetkilendirme yapısı için [resmî Google Drive backend dokümantasyonuna](https://rclone.org/drive/) bakın.

Remote adının root tarafından görülebildiğini config içeriğini göstermeden kontrol edin:

```bash
sudo rclone --config /etc/rclone/odoo-rclone.conf listremotes
sudo rclone --config /etc/rclone/odoo-rclone.conf lsd '<RCLONE_REMOTE>:<REMOTE_PATH>'
```

**Beklenen sonuç:** Yapılandırılmış remote listelenir ve hedef klasör
okunabilir. `rclone config show` veya config dosyasını yazdıran komut
kullanmayın.

#### 2. Environment ayarlarını doğrulama

`/etc/odoo/deployment.env` içinde yalnız secret olmayan yollar bulunur:

```dotenv
RCLONE_CONFIG=/etc/rclone/odoo-rclone.conf
OFFSITE_REMOTE=<RCLONE_REMOTE>:<REMOTE_PATH>
```

OAuth token bu environment dosyasına yazılmaz.

#### 3. Manuel off-site upload testi

Önce en az bir tamamlanmış local backup seti bulunduğunu doğrulayın, ardından scripti çalıştırın:

```bash
sudo find /var/backups/odoo -mindepth 1 -maxdepth 1 -type d -name 'odoo_production_20*' -print
sudo /opt/odoo/project/deployment/scripts/offsite_backup.sh
```

Script her sette dört beklenen dosyayı, `root:root 0600` izinlerini ve SHA-256 manifestini doğrular. Uzak set zaten eksiksizse tekrar transfer etmez. Eksikse yalnız `.dump`, `.tar.gz`, `.metadata` ve `.sha256` dosyalarını `copyto --immutable` ile gönderir. Değiştirilmiş aynı adlı remote dosyanın üzerine yazmak yerine hata verir.

Belirli bir seti local ve remote arasında ayrıca kontrol edin:

```bash
sudo rclone --config /etc/rclone/odoo-rclone.conf check \
  /var/backups/odoo/SET_NAME \
  '<RCLONE_REMOTE>:<REMOTE_PATH>/SET_NAME' \
  --one-way
```

#### 4. Off-site systemd service ve timer kurulumu

```bash
sudo chmod 0755 /opt/odoo/project/deployment/scripts/offsite_backup.sh
sudo cp /opt/odoo/project/deployment/odoo-offsite-backup.service /etc/systemd/system/odoo-offsite-backup.service
sudo cp /opt/odoo/project/deployment/odoo-offsite-backup.timer /etc/systemd/system/odoo-offsite-backup.timer
sudo systemd-analyze verify /etc/systemd/system/odoo-offsite-backup.service /etc/systemd/system/odoo-offsite-backup.timer
sudo systemctl daemon-reload
```

Önce service'i manuel test edin:

```bash
sudo systemctl start odoo-offsite-backup.service
sudo systemctl status odoo-offsite-backup.service --no-pager
sudo journalctl -u odoo-offsite-backup.service -n 100 --no-pager
```

Test başarılı olduktan sonra ayrı timer'ı etkinleştirin:

```bash
sudo systemctl enable --now odoo-offsite-backup.timer
sudo systemctl list-timers odoo-backup.timer odoo-offsite-backup.timer
```

Local timer gece yarısı civarında çalışır. Off-site timer günlük `02:00` sonrasında en fazla 30 dakikalık rastgele gecikmeyle çalışır ve `Persistent=true` kullanır. İki timer ayrı kalır; off-site service local backup service'i çağırmaz.

#### 5. Hata inceleme ve restore sorumluluğu

Upload hatalarını incelemek için:

```bash
sudo systemctl status odoo-offsite-backup.service --no-pager
sudo journalctl -u odoo-offsite-backup.service --since today --no-pager
sudo systemctl list-timers odoo-offsite-backup.timer
```

Remote servis veya ağ kesintisi sırasında off-site service non-zero döner.
Local set silinmez veya değiştirilmez; sonraki timer çalışması eksik seti
yeniden dener. Uzun süreli kesintilerin local retention süresini aşmaması
için journal/systemd failure takibi yapılmalıdır.

Mevcut remote doğrudan rclone backend'i üzerinden kullanılıyorsa ve ayrıca
bir `crypt` remote tanımlı değilse client-side şifreleme sağlamaz. Remote
hesabında güçlü parola, MFA ve sınırlı erişim uygulanmalıdır. İleride
client-side encryption istenirse ayrı bir `crypt` remote staging restore ile
test edilmeden production hedefi sessizce değiştirilmemelidir.

Local restore testi ve remote'dan korumalı bir staging dizinine indirilmiş
off-site setle restore testi ayrı ayrı yapılmalıdır. Off-site upload işlemi
local veya remote backup dosyalarını silmez. Off-site backup ancak indirme,
checksum ve staging restore provasıyla tam olarak doğrulanmış sayılır.

## 25. Restore testi

**Nerede:** VPS SSH terminali, production dışı staging adı

En son backup dizinini seçip:

```bash
sudo /opt/odoo/project/deployment/scripts/restore.sh --backup-dir /var/backups/odoo/DATABASE_NAME_YYYYMMDD_HHMMSS --target-db odoo_restore_test
sudo -u postgres psql -d odoo_restore_test -c "SELECT name, state, latest_version FROM ir_module_module WHERE name IN ('ardaapp','internship_logbook','sales_app','course_student_management') ORDER BY name;"
sudo find /var/lib/odoo/filestore/odoo_restore_test -type f | wc -l
```

Registry yükleme kontrolü:

```bash
sudo -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin --config=/etc/odoo/odoo.conf --database=odoo_restore_test --stop-after-init --no-http
```

Production service bu staging DB'ye bağlanmaz. Tam UI testi için ayrı staging config/service/port kullanın.

Test DB ve filestore'u silmeden önce restore sonuçlarını kayıt altına alın ve doğru hedefi iki kez doğrulayın.

## 26. Production cutover

**Nerede:** Windows source, VPS ve DNS/browser

Kesin sıra:

1. Bakım penceresini başlatın.
2. Windows Odoo'ya yeni yazma girişini durdurun.
3. Final PostgreSQL 17 dump alın.
4. Odoo duruyorken eşleşen final filestore arşivini alın.
5. Checksum ve metadata üretin.
6. Backup'ı VPS'e ve off-site konuma kopyalayın.
7. VPS'te checksum doğrulayın.
8. `restore.sh --production --replace-existing` ile restore edin.
9. Production'da kullanılan `internship_logbook` modülünü upgrade edin:

```bash
sudo systemctl stop odoo.service
sudo -u odoo \
  /opt/odoo/venv/bin/python3 \
  /opt/odoo/odoo/odoo-bin \
  -c /etc/odoo/odoo.conf \
  -d odoo_production \
  -u internship_logbook \
  --stop-after-init
sudo systemctl start odoo.service
```

10. HTTPS/login/mail/PDF/attachment smoke testlerini tamamlayın.
11. Eski Windows sistemini hemen silmeyin; salt-okunur rollback kaynağı olarak saklayın.
12. Kabul onayından sonra maintenance penceresini kapatın.

---

## Sonraki custom kod güncellemeleri

Canonical ve güncel prosedür
[MAINTENANCE_RUNBOOK.md](MAINTENANCE_RUNBOOK.md#4-canonical-gelecek-deployment-akışı)
içindedir.

Özet sıra:

1. Windows'ta geliştir, test et, diff/secret kontrolü yap.
2. Feature branch kullanıldıysa review sonrasında `main` branch'ine merge et.
3. Production health ve temiz Git working tree kontrolü yap.
4. Tutarlı local backup alıp SHA-256 sonucunu doğrula.
5. Yalnız fast-forward pull yap:

```bash
sudo -u odoo git -C /opt/odoo/project pull --ff-only
```

6. Odoo'yu durdurup yalnız etkilenen modülü upgrade et:

```bash
sudo systemctl stop odoo.service

sudo -u odoo \
  /opt/odoo/venv/bin/python3 \
  /opt/odoo/odoo/odoo-bin \
  -c /etc/odoo/odoo.conf \
  -d odoo_production \
  -u internship_logbook \
  --stop-after-init

sudo systemctl start odoo.service
```

7. Service/log/HTTPS ve uygulama smoke testlerini tamamla.
8. AI değiştiyse secret göstermeden gerçek Gemini smoke testi yap.
9. Theme, logo veya frontend asset değiştiyse browser hard refresh/cache
   kontrolü yap.

Production'da doğrudan kod geliştirmeyin, force-pull veya rastgele
`reset --hard` kullanmayın.

## Odoo core update prosedürü

Odoo core update, `update.sh` kapsamı dışındadır.

1. Yeni Odoo commit'i staging'de test edin.
2. DB+filestore backup alın.
3. `ODOO_COMMIT` değişiklik kaydını hazırlayın.
4. Maintenance penceresinde core checkout'u yeni SHA'ya alın.
5. Gerekli module upgrade ve tam regresyon testini yapın.
6. Başarısızsa eski SHA ve backup setine dönün.

Branch HEAD'e otomatik geçiş yapmayın.

## Rollback planı

Rollback öncesinde durun ve sorunun kapsamını değerlendirin. Tam known-good
Git commit ile ona karşılık gelen database+filestore backup setini birlikte
belirleyin. Restore öncesinde SHA-256 doğrulayın; attachment tutarlılığı
önemliyken database'i eşleşen filestore olmadan restore etmeyin. Ayrıntılı
operasyon sırası:
[Maintenance Runbook — Conservative rollback](MAINTENANCE_RUNBOOK.md#11-conservative-rollback).

### Deployment veya module upgrade başarısızsa

1. Hata logunu, deployment öncesi ve sonrası custom commit SHA'larını kaydedin.
2. Registry/module upgrade tamamlanmadıysa Odoo'yu otomatik olarak yeniden
   açmayın.
3. Kodun tek başına geri alınmasının yeterli olup olmadığını değerlendirin;
   database şeması veya data upgrade başladıysa pre-deployment database ve
   filestore backup'ını eşleşen çift olarak kullanın.
4. SHA-256 doğrulaması yapılmadan restore başlatmayın.
5. Known-good commit ve backup seti kesinleştikten sonra
   [Maintenance Runbook](MAINTENANCE_RUNBOOK.md#11-conservative-rollback)
   adımlarını izleyin.
6. Registry, login, workflow, attachment ve HTTPS testleri başarılı olmadan
   production trafiğini yeniden açmayın.

### Production restore başarısızsa

`restore.sh` mevcut production DB ve filestore'u şu biçimde korur:

```text
DATABASE_NAME_pre_restore_YYYYMMDD_HHMMSS
/var/lib/odoo/filestore/DATABASE_NAME.pre_restore_YYYYMMDD_HHMMSS
```

Servis stopped kalır. Yeni/başarısız DB'yi hemen silmeyin. PostgreSQL yöneticisiyle:

1. Başarısız DB'yi farklı bir adla koruyun.
2. `pre_restore` DB'yi yeniden production adına çevirin.
3. Yeni filestore'u farklı adla koruyun.
4. `pre_restore` filestore'u production adına geri alın.
5. Kod commit'lerini eşleştirin.
6. Servisi başlatıp test edin.

Rollback kopyaları ancak production kabulü, off-site backup ve restore kanıtı tamamlandıktan sonra kaldırılmalıdır.
