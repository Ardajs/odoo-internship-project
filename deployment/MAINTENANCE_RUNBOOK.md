# Odoo 19 Production Maintenance Runbook

Bu runbook, canlı `stajdefterim.site` ortamının günlük işletimi, güvenli
uygulama güncellemesi, AI yapılandırması, backup kontrolü ve rollback hazırlığı
içindir. İlk kurulum veya tamamen yeni sunucu kurulumu için
[DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) kullanılmalıdır.

> Production üzerinde doğrudan geliştirme yapmayın. Kod, tema ve logo
> değişikliklerini önce Windows geliştirme ortamında test edin; Git review ve
> `main` merge sonrasında production'a alın.

## 1. Doğrulanmış production mimarisi

```text
Internet
  |
  v
https://stajdefterim.site
  |
  v
Nginx :443
  |-- Odoo HTTP      -> 127.0.0.1:8069
  `-- WebSocket      -> 127.0.0.1:8072
                         |
                         v
                      Odoo 19 Community
                         |
                         v
                      PostgreSQL (local)
```

```text
Odoo core:              /opt/odoo/odoo
Custom repository:      /opt/odoo/project
Python virtualenv:       /opt/odoo/venv
Odoo configuration:     /etc/odoo/odoo.conf
AI environment:         /etc/odoo/odoo-ai.env
AI systemd drop-in:      /etc/systemd/system/odoo.service.d/ai.conf
Database:                odoo_production
Filestore:               /var/lib/odoo/filestore/odoo_production
Odoo logs:               /var/log/odoo
Local backups:           /var/backups/odoo
Application module:      /opt/odoo/project/dev_addonsI/internship_logbook
```

Production Git checkout'u `main` branch'ini takip eder. Odoo
`odoo.service`, reverse proxy Nginx ve veritabanı PostgreSQL tarafından
yönetilir. HTTP, HTTPS'e yönlenir; HTTPS isteği Odoo'nun `/odoo` yoluna
yönlendirmesiyle sonuçlanabilir.

## 2. Hızlı sağlık kontrolü

**Nerede:** Ubuntu production VPS, SSH terminali

```bash
sudo systemctl is-enabled postgresql odoo nginx \
  odoo-backup.timer odoo-offsite-backup.timer certbot.timer

sudo systemctl is-active postgresql odoo nginx \
  odoo-backup.timer odoo-offsite-backup.timer certbot.timer
```

Beklenen sonuç tüm birimler için sırasıyla `enabled` ve `active` değeridir.

Servis ve socket ayrıntıları:

```bash
sudo systemctl status odoo.service nginx.service postgresql.service --no-pager
sudo ss -lntp | grep -E ':80|:443|:8069|:8072|:5432'
curl --fail --silent --show-error http://127.0.0.1:8069/web/login -o /dev/null
```

`8069` ve `8072` yalnız localhost üzerinde, PostgreSQL ise yalnız güvenli
local bağlantı üzerinde olmalıdır. Bu portlara public firewall kuralı
eklenmemelidir.

Public HTTP/HTTPS kontrolü:

```bash
curl --silent --show-error --output /dev/null \
  --write-out 'HTTP %{http_code} -> %{redirect_url}\n' \
  http://stajdefterim.site

curl --silent --show-error --output /dev/null \
  --write-out 'HTTPS %{http_code} -> %{redirect_url}\n' \
  https://stajdefterim.site
```

HTTP isteği HTTPS'e yönlenmeli; HTTPS isteği başarılı bir Odoo yanıtı veya
`/odoo` yönlendirmesi vermelidir.

## 3. Site erişilemiyorsa

Önce teşhis yapın; servisi körlemesine tekrar tekrar başlatmayın.

```bash
sudo systemctl status postgresql odoo nginx --no-pager
sudo journalctl -u odoo.service -n 200 --no-pager
sudo journalctl -u nginx.service -n 100 --no-pager
sudo tail -n 200 /var/log/odoo/odoo.log
sudo tail -n 100 /var/log/nginx/odoo.error.log
sudo nginx -t
sudo ss -lntp | grep -E ':443|:8069|:8072|:5432'
df -h
free -h
swapon --show
```

Kontrol sırası:

1. PostgreSQL aktif mi?
2. Odoo registry hatasız yüklenmiş mi?
3. Odoo yalnız `127.0.0.1:8069` ve `127.0.0.1:8072` üzerinde dinliyor mu?
4. Nginx yapılandırması geçerli mi?
5. Disk veya RAM tükenmiş mi?
6. Sertifika süresi ve `certbot.timer` sağlıklı mı?
7. Production Git çalışma ağacı beklenmedik biçimde kirli mi?

Sorun anlaşıldıktan sonra gerekiyorsa kontrollü yeniden başlatın:

```bash
sudo systemctl restart odoo.service
sudo systemctl status odoo.service --no-pager
sudo journalctl -u odoo.service -n 100 --no-pager
```

## 4. Canonical gelecek deployment akışı

### 4.1 Windows local development

**Nerede:** Windows PowerShell, repository kökü

1. Uygun olduğunda feature branch oluşturun.
2. Değişikliği geliştirin ve local Odoo 19 üzerinde test edin.
3. İlgili automated testleri çalıştırın.
4. Diff ve secret kontrolü yapın.
5. Commit ve push yapın.
6. Feature branch kullanıldıysa review sonrasında `main` branch'ine merge edin.

Temel Git kontrolleri:

```powershell
Set-Location -LiteralPath "C:\path\to\Odoo"
git status --short --branch
git diff --check
git diff
git diff --cached --check
```

Gerçek API key, password, token, private key, `.env`, `odoo.conf`, database
dump veya filestore hiçbir zaman stage edilmemelidir.

### 4.2 Ubuntu production

**Nerede:** Ubuntu production VPS, SSH terminali

1. Sağlık kontrollerini çalıştırın.
2. Git checkout'un `main` branch'inde ve temiz olduğunu doğrulayın.
3. Tutarlı local backup oluşturup doğrulayın.
4. Gerekliyse off-site kopyanın korunduğunu doğrulayın.
5. Yalnız fast-forward pull yapın.
6. Odoo'yu durdurun.
7. Yalnız etkilenen modülleri upgrade edin.
8. Odoo'yu başlatın.
9. Service, log ve HTTPS kontrollerini yapın.
10. Uygulama smoke testlerini tamamlayın.

Git ön kontrolü:

```bash
sudo -u odoo git -C /opt/odoo/project branch --show-current
sudo -u odoo git -C /opt/odoo/project status --short
sudo -u odoo git -C /opt/odoo/project rev-parse HEAD
```

Beklenen branch `main`, `status --short` çıktısı ise boş olmalıdır. Kirli
working tree varsa deployment'ı durdurun; `reset --hard`, force-pull veya
production dosyalarını elle değiştirme yoluna gitmeyin.

Deployment öncesi local backup:

```bash
sudo systemctl start odoo-backup.service
sudo systemctl show odoo-backup.service \
  --property=Result --property=ExecMainStatus --no-pager
sudo journalctl -u odoo-backup.service -n 100 --no-pager
```

Fast-forward update:

```bash
sudo -u odoo git -C /opt/odoo/project pull --ff-only
```

`internship_logbook` upgrade örneği:

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

Son kontroller:

```bash
sudo systemctl status odoo.service --no-pager
sudo journalctl -u odoo.service -n 150 --no-pager
curl --silent --show-error --output /dev/null \
  --write-out '%{http_code} %{redirect_url}\n' \
  https://stajdefterim.site
sudo -u odoo git -C /opt/odoo/project status --short --branch
```

Smoke test kapsamında login, intern/supervisor yetkileri, Daily Entry
submit/revision/resubmit/approve, e-posta kuyruğu, PDF ve attachment
kontrol edilmelidir. AI değiştiyse gerçek Gemini çağrısıyla bir Improve
Writing ve Apply Suggestion testi yapın; secret veya prompt içeriğini loglara
yazdırmayın. Frontend/theme/assets değiştiyse tarayıcıda hard refresh yapın.

## 5. Gemini AI production yapılandırması

Production provider `gemini` olmalıdır; `mock` yalnız local geliştirme ve
otomatik test içindir.

Odoo service şu drop-in üzerinden korumalı environment dosyasını yükler:

```text
/etc/systemd/system/odoo.service.d/ai.conf
EnvironmentFile=/etc/odoo/odoo-ai.env
```

`/etc/odoo/odoo-ai.env` Git'e eklenmez, frontend'e sunulmaz ve Odoo server
process'i dışında paylaşılmaz. Önerilen koruma:

```bash
sudo chown root:root /etc/odoo/odoo-ai.env
sudo chmod 0600 /etc/odoo/odoo-ai.env
sudo stat -c '%U:%G %a %n' /etc/odoo/odoo-ai.env
sudo systemctl show odoo.service --property=EnvironmentFiles --no-pager
```

Environment dosyasındaki kavramsal yapı:

```dotenv
INTERNSHIP_AI_ENABLED=True
INTERNSHIP_AI_PROVIDER=gemini
INTERNSHIP_AI_API_KEY=<GEMINI_API_KEY>
INTERNSHIP_AI_MODEL=<GEMINI_MODEL>
INTERNSHIP_AI_GEMINI_ENDPOINT=<GEMINI_ENDPOINT>
INTERNSHIP_AI_TIMEOUT=<TIMEOUT_SECONDS>
INTERNSHIP_AI_MAX_INPUT_CHARS=<MAX_INPUT_CHARS>
INTERNSHIP_AI_MAX_OUTPUT_TOKENS=<MAX_OUTPUT_TOKENS>
INTERNSHIP_AI_MAX_OUTPUT_CHARS=<MAX_OUTPUT_CHARS>
```

Gerçek API key'i terminale, dokümana, Git'e, browser config'e veya Odoo
chatter'a yazmayın. Protected environment önceliklidir; uygulamadaki kontrollü
System Parameters fallback yalnız yönetim ihtiyacı varsa kullanılmalıdır.

AI ayarı değiştirilmesi gerekiyorsa dosyayı repository içinde değil, sunucuda
yetkili bir yönetici olarak `sudoedit /etc/odoo/odoo-ai.env` ile düzenleyin.
Değişiklikten sonra izinleri yeniden doğrulayın ve Odoo'yu kontrollü yeniden
başlatın:

```bash
sudo chown root:root /etc/odoo/odoo-ai.env
sudo chmod 0600 /etc/odoo/odoo-ai.env
sudo systemctl daemon-reload
sudo systemctl restart odoo.service
sudo systemctl status odoo.service --no-pager
```

Environment dosyasının içeriğini `cat`, `grep`, `systemctl show
--property=Environment` veya shell debug çıktısıyla yazdırmayın.

### API key'i göstermeden çalışan process'i doğrulama

Aşağıdaki komut yalnız non-secret allowlist değerlerini yazdırır ve API
key'in sadece mevcut olup olmadığını gösterir:

```bash
sudo python3 - <<'PY'
from pathlib import Path
import subprocess

pid = subprocess.check_output(
    ["systemctl", "show", "--property=MainPID", "--value", "odoo.service"],
    text=True,
).strip()
if not pid or pid == "0":
    raise SystemExit("odoo.service is not running")

items = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
environment = {}
for item in items:
    if b"=" in item:
        name, value = item.split(b"=", 1)
        environment[name.decode(errors="replace")] = value.decode(errors="replace")

non_secret_names = (
    "INTERNSHIP_AI_ENABLED",
    "INTERNSHIP_AI_PROVIDER",
    "INTERNSHIP_AI_MODEL",
    "INTERNSHIP_AI_GEMINI_ENDPOINT",
    "INTERNSHIP_AI_TIMEOUT",
    "INTERNSHIP_AI_MAX_INPUT_CHARS",
    "INTERNSHIP_AI_MAX_OUTPUT_TOKENS",
    "INTERNSHIP_AI_MAX_OUTPUT_CHARS",
)
for name in non_secret_names:
    print(f"{name}={environment.get(name, '<missing>')}")

key_state = "<set>" if environment.get("INTERNSHIP_AI_API_KEY") else "<missing>"
print(f"INTERNSHIP_AI_API_KEY={key_state}")
PY
```

Beklenen sonuç provider için `gemini`, enabled için `True`/eşdeğer aktif
değer ve API key için yalnız `<set>` bilgisidir.

AI smoke testinde:

- Intern yalnız kendi draft/revision entry'sinde AI kullanabilmelidir.
- Supervisor AI butonlarını görmemelidir.
- Submitted/Approved entry'ye eski wizard üzerinden apply reddedilmelidir.
- Suggestions/Missing Details business field değiştirmemelidir.
- API key veya raw provider response kullanıcıya gösterilmemelidir.

Gemini quota, rate limit, billing ve maliyet alarmları Google tarafında ayrıca
izlenmelidir.

## 6. MuK theme bakım akışı

Production'da şu modüller kuruludur:

- `muk_web_theme`
- `muk_web_group`
- `muk_web_chatter`
- `muk_web_dialog`
- `muk_web_appsbar`
- `muk_web_colors`
- `muk_web_refresh`

`muk_web_theme`, diğer altı destek modülüne bağımlıdır.

Tema değişikliği:

1. Değişikliği local ortamda yapın ve browser asset davranışını test edin.
2. Git diff'i review edip commit/push yapın.
3. Feature branch kullanıldıysa `main` merge'ini tamamlayın.
4. Production'da tutarlı backup oluşturup doğrulayın.
5. `sudo -u odoo git -C /opt/odoo/project pull --ff-only` çalıştırın.
6. Odoo'yu durdurun.
7. Yalnız değişen MuK modülü ve gerekiyorsa `muk_web_theme` modülünü upgrade edin.
8. Odoo'yu başlatıp service ve HTTPS'i doğrulayın.
9. Browser'da hard refresh/cache testi yapın.

Örnek upgrade:

```bash
sudo systemctl stop odoo.service

sudo -u odoo \
  /opt/odoo/venv/bin/python3 \
  /opt/odoo/odoo/odoo-bin \
  -c /etc/odoo/odoo.conf \
  -d odoo_production \
  -u muk_web_theme,muk_web_colors \
  --stop-after-init

sudo systemctl start odoo.service
sudo systemctl status odoo.service --no-pager
```

Modül listesini gerçek değişikliğe göre daraltın. Production theme dosyalarını
doğrudan düzenlemeyin.

## 7. Internship Logbook logo güncellemesi

Application icon repository yolu:

```text
dev_addonsI/internship_logbook/static/src/img/internship.png
```

Menü tanımı:

```xml
web_icon="internship_logbook,static/src/img/internship.png"
```

Güvenli güncelleme:

1. Local `internship.png` dosyasını aynı isimle değiştirin.
2. Local Odoo'da format, boyut ve görünümü test edin.
3. `git status --short` ve `git diff --stat` ile değişikliği doğrulayın.
4. Commit/push ve gerekiyorsa `main` merge yapın.
5. Production backup'ını doğrulayın.
6. Production'da `git pull --ff-only` çalıştırın.
7. `internship_logbook` modülünü upgrade edin.
8. Odoo'yu yeniden başlatın.
9. Browser hard refresh yapın; gerekirse site verisi/asset cache'ini kontrollü
   temizleyip tekrar doğrulayın.

Logo dosyasını doğrudan production checkout'unda değiştirmeyin.

## 8. Local backup doğrulama

Backup root:

```text
/var/backups/odoo
```

Tamamlanmış set örneği:

```text
/var/backups/odoo/odoo_production_TIMESTAMP/
```

Set; PostgreSQL custom-format dump, aynı ana ait filestore arşivi, metadata ve
SHA-256 manifest içermelidir. Tutarlılık gerektiğinde backup süreci Odoo'yu
kısa süre durdurur. Tamamlanmış local setler için retention şu anda 7 gündür.

Timer ve son çalışma:

```bash
sudo systemctl status odoo-backup.timer --no-pager
sudo systemctl list-timers --all odoo-backup.timer
sudo journalctl -u odoo-backup.service --since '7 days ago' --no-pager
```

En yeni tamamlanmış set:

```bash
sudo find /var/backups/odoo \
  -mindepth 1 -maxdepth 1 -type d \
  -name 'odoo_production_*' \
  -printf '%T@ %p\n' | sort -nr | head -n 1
```

SHA-256 doğrulama:

```bash
sudo bash -c '
latest="$(find /var/backups/odoo -mindepth 1 -maxdepth 1 -type d \
  -name "odoo_production_*" -printf "%T@ %p\n" |
  sort -nr | head -n 1 | cut -d" " -f2-)"
test -n "$latest" || { echo "No completed backup set found"; exit 1; }
manifest="$(find "$latest" -maxdepth 1 -type f -name "*.sha256" -print -quit)"
test -n "$manifest" || { echo "SHA-256 manifest missing"; exit 1; }
echo "Verifying: $latest"
cd "$latest"
sha256sum --check "$(basename "$manifest")"
'
```

Sadece VPS'te bulunan backup yeterli değildir.

## 9. Off-site backup doğrulama

Off-site upload local backup'tan bağımsızdır. Ağ veya remote kesintisi,
tamamlanmış local backup sonucunu başarısız saydırmamalıdır.

```bash
sudo systemctl status odoo-offsite-backup.timer --no-pager
sudo systemctl list-timers --all odoo-offsite-backup.timer
sudo journalctl -u odoo-offsite-backup.service \
  --since '7 days ago' --no-pager
```

Manuel doğrulama gerektiğinde:

```bash
sudo systemctl start odoo-offsite-backup.service
sudo systemctl show odoo-offsite-backup.service \
  --property=Result --property=ExecMainStatus --no-pager
sudo journalctl -u odoo-offsite-backup.service -n 150 --no-pager
```

Off-site süreç:

- Local SHA-256 manifestini upload öncesinde doğrular.
- Yalnız tamamlanmış backup setlerini işler.
- Eksiksiz remote setleri yeniden yüklemez.
- Başarılı çalışmada doğrulanan setleri loglar.
- Local backup setlerini değiştirmez veya silmez.
- Bu tasarımda remote backup silmez.

Rclone remote credential, OAuth token ve protected config içeriğini loglara
veya dokümantasyona yazmayın. Local ve off-site restore provalarını periyodik
olarak ayrı ayrı gerçekleştirin.

## 10. TLS ve Certbot

```bash
sudo systemctl status certbot.timer --no-pager
sudo systemctl list-timers --all certbot.timer
sudo journalctl -u certbot.service --since '30 days ago' --no-pager
sudo certbot renew --dry-run
```

`certbot.timer` enabled ve active olmalıdır. `renew --dry-run` sonucu
başarısızsa sertifika süresi dolmadan DNS, Nginx challenge ve firewall
durumunu düzeltin.

## 11. Conservative rollback

Rollback sırasında aceleyle `reset --hard`, database drop veya filestore
silme işlemi yapmayın.

1. Production trafiğini ve yazma riskini değerlendirin; gerekiyorsa Odoo'yu
   durdurun.
2. Hatanın kod, config, database şeması veya external provider kaynaklı
   olduğunu belirleyin.
3. Tam known-good Git commit SHA'yı kaydedin.
4. O commit ile eşleşen pre-deployment database+filestore backup setini seçin.
5. SHA-256 manifestini doğrulayın.
6. Database ve filestore'u eşleşen çift olarak ele alın.
7. [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) ve mevcut
   `deployment/scripts/restore.sh` prosedürünü izleyin; doğaçlama restore
   komutları kullanmayın.
8. Restore sonrasında kod commit'i, database adı ve
   `/var/lib/odoo/filestore/odoo_production` eşleşmesini doğrulayın.
9. Production trafiğini açmadan önce `--stop-after-init` ile registry/module
   state kontrolü yapın.
10. Login, workflow, mail, PDF, attachment ve gerekiyorsa AI smoke testlerini
    tamamlayın.

Attachment tutarlılığı önemliyken database'i karşılık gelen filestore olmadan
restore etmeyin. Başarısız/yarım kaynakları hemen silmeyin; inceleme ve
recovery için koruyun.

## 12. Routine maintenance checklist

Günlük/haftalık:

- [ ] `odoo.service` active ve son loglarda kritik hata yok.
- [ ] PostgreSQL active ve yalnız güvenli local erişimde.
- [ ] Nginx active; HTTP→HTTPS ve `/odoo` yönlendirmesi çalışıyor.
- [ ] Disk kullanımı ve inode kapasitesi güvenli seviyede.
- [ ] RAM/swap baskısı veya OOM kaydı yok.
- [ ] Production Git branch `main` ve working tree temiz.
- [ ] Son local backup tamamlanmış ve SHA-256 doğrulanmış.
- [ ] `odoo-backup.timer` active ve son koşu başarılı.
- [ ] `odoo-offsite-backup.timer` active ve son upload başarılı.

Aylık/periyodik:

- [ ] `certbot.timer` active; renewal durumu kontrol edildi.
- [ ] AI process environment'ında Gemini provider ve API key presence doğrulandı.
- [ ] Gemini quota, rate limit, billing ve maliyet alarmı provider tarafında kontrol edildi.
- [ ] Odoo error log trendleri incelendi.
- [ ] Local ve off-site backup kapasite/retention durumu incelendi.
- [ ] Staging üzerinde database+filestore restore provası yapıldı veya takvimi güncel.
- [ ] Attachment, PDF, e-posta ve kritik workflow smoke testleri tekrarlandı.

## 13. Security özeti

- Secret'ları Git'e commit etmeyin.
- Diagnostic sırasında API key veya token değerini yazdırmayın.
- `/etc/odoo/odoo-ai.env` restrictive owner/mode ile korunmalıdır.
- Secret'lar Odoo'ya yalnız server-side verilmelidir.
- Production'da `mock` AI provider kullanmayın.
- Production kodunu, theme dosyalarını veya logoyu doğrudan düzenlemeyin.
- PostgreSQL, Odoo HTTP ve websocket portlarını public açmayın.
- HTTPS ve Certbot renewal kontrolünü sürdürün.
- Backup'ları off-site koruyun.
- Restore prosedürünü periyodik olarak gerçekten test edin.
