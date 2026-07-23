# Odoo Custom Project Production Test Planı

Bu plan önce staging restore üzerinde, ardından production cutover sonrasında smoke-test kapsamıyla uygulanmalıdır. Test sonuçlarında tarih, kullanıcı, commit SHA, database adı, beklenen sonuç ve gerçek sonuç kaydedilmelidir.

## Test rolleri ve veriler

En az şu ayrı kullanıcıları hazırlayın:

- Sistem yöneticisi
- Internship Manager
- Internship Supervisor A
- Internship Supervisor B
- Intern A
- Intern B
- Yetkisiz normal internal user

Intern A ve Intern B farklı `internship.student` kayıtlarına bağlanmalıdır. Supervisor A yalnız kendi programına atanmalıdır. Böylece record rule izolasyonu gerçek biçimde test edilir.

## 1. Platform ve login

| ID | Test | Beklenen sonuç |
|---|---|---|
| PLT-01 | HTTPS üzerinden admin login | Giriş başarılı; URL HTTPS olarak kalır |
| PLT-02 | Hatalı parola | Giriş reddedilir, secret/log sızıntısı olmaz |
| PLT-03 | Database selector URL'leri | `list_db=False` nedeniyle database listesi gösterilmez |
| PLT-04 | Intern/Supervisor/Manager ayrı login | Her kullanıcı yalnız rolüne uygun menü ve kayıtları görür |
| PLT-05 | Reboot/service restart sonrası login | Session yeniden kurulabilir, servis sağlıklıdır |

## 2. Internship Logbook — CRUD ve yetkiler

### `internship.student`

| ID | Rol/işlem | Beklenen sonuç |
|---|---|---|
| INT-STU-01 | Manager student oluşturur | Kayıt başarıyla oluşur |
| INT-STU-02 | Aynı student number tekrar oluşturulur | Unique constraint hatası alınır |
| INT-STU-03 | Intern kendi student kaydını okur | Yalnız kendine bağlı kaydı görür |
| INT-STU-04 | Intern başka student kaydını açmayı dener | Record rule erişimi engeller |
| INT-STU-05 | Supervisor atanmış student'ı okur | Okuma başarılıdır |
| INT-STU-06 | Supervisor atanmamış student'ı açar | Erişim engellenir |
| INT-STU-07 | Intern/Supervisor student silmeyi dener | ACL işlemi engeller |
| INT-STU-08 | Manager student update/delete | Yetki ve bağlı kayıt etkileri beklendiği gibidir |

### `internship.program`

| ID | Test | Beklenen sonuç |
|---|---|---|
| INT-PRG-01 | Manager geçerli program oluşturur | Student, supervisor ve tarihler kaydedilir |
| INT-PRG-02 | Bitiş tarihi başlangıçtan önce | ValidationError alınır |
| INT-PRG-03 | Aynı student için çakışan program | Overlap constraint engeller |
| INT-PRG-04 | Draft program başlatılır | State `active` olur |
| INT-PRG-05 | Onaylanmamış entry varken tamamlanır | Tamamlama engellenir |
| INT-PRG-06 | En az bir approved entry ile tamamlanır | State `completed` olur |
| INT-PRG-07 | Supervisor yalnız atanmış programı görür | Record rule doğru uygulanır |
| INT-PRG-08 | Intern yalnız kendi programını görür | Record rule doğru uygulanır |

### `internship.daily.entry`

| ID | Test | Beklenen sonuç |
|---|---|---|
| INT-DAY-01 | Intern aktif programda entry oluşturur | Kayıt draft oluşur, day number hesaplanır |
| INT-DAY-02 | Program tarih aralığı dışında entry | ValidationError alınır |
| INT-DAY-03 | Aynı program/tarih ikinci entry | Unique constraint engeller |
| INT-DAY-04 | Work hours 0 veya 24'ten büyük | ValidationError alınır |
| INT-DAY-05 | Intern draft/revision entry günceller | Update başarılıdır |
| INT-DAY-06 | Intern başkasının entry'sini okur/yazar | Record rule engeller |
| INT-DAY-07 | Intern entry silmeyi dener | ACL engeller |
| INT-DAY-08 | Manager CRUD uygular | Tüm yetkili işlemler başarılıdır |

## 3. Submit, approve ve revision akışı

| ID | Adım | Beklenen sonuç |
|---|---|---|
| FLOW-01 | Intern draft entry'yi submit eder | State `submitted`, chatter mesajı ve supervisor activity oluşur |
| FLOW-02 | Draft/active olmayan programda submit | İşlem engellenir |
| FLOW-03 | Yetkisiz normal user submit eder | AccessError alınır |
| FLOW-04 | Atanmış supervisor submitted entry'yi approve eder | State `approved`, activity tamamlanır, chatter mesajı oluşur |
| FLOW-05 | Başka supervisor approve etmeyi dener | Record rule veya erişim kontrolü engeller |
| FLOW-06 | Supervisor comment olmadan revision ister | İşlem hata verir ve state değişikliği transaction ile geri alınır |
| FLOW-07 | Comment ile revision istenir | State `revision`, intern activity ve e-posta kuyruğu oluşur |
| FLOW-08 | Intern revision kaydını düzeltip tekrar submit eder | State `submitted`, revision activity tamamlanır |
| FLOW-09 | Toplu/multi-record revision çağrısı | Son kayıt dışındaki activity/e-posta davranışı ayrıca incelenir |

## 3A. AI Writing Assistant — Gemini production smoke testi

Production'da provider `gemini` olmalı; `mock` provider kullanılmamalıdır.
Test sırasında API key, prompt, ham provider cevabı veya günlük metni loglara
yazdırılmamalıdır.

| ID | Rol/işlem | Beklenen sonuç |
|---|---|---|
| AI-01 | Intern kendi draft entry'sinde Improve Writing açar | Wizard açılır; öneri üretilirken entry otomatik değişmez |
| AI-02 | Intern Apply Suggestion kullanır | Yalnız `work_description` güncellenir; state ve diğer alanlar değişmez |
| AI-03 | Improve Learning Summary | Yalnız `learned_topics` güncellenir |
| AI-04 | Improve Problems & Solutions | Yalnız `challenges` güncellenir |
| AI-05 | Give Suggestions / Find Missing Details | Feedback oluşur; hiçbir business field otomatik güncellenmez |
| AI-06 | Revision Assistant | Yalnız revision state'inde görünür; supervisor comment değiştirilmez |
| AI-07 | Regenerate | Güncel kaynak metinden yeni öneri oluşur; otomatik apply yapılmaz |
| AI-08 | Submitted/approved entry | AI butonları görünmez; eski wizard üzerinden apply backend tarafından reddedilir |
| AI-09 | Supervisor hesabı | Entry'yi workflow kapsamında görebilir ancak AI kullanamaz |
| AI-10 | Intern başka intern'in entry'si | Record rule erişimi engeller |
| AI-11 | Stale suggestion | Hedef alan başka sekmede değişmişse eski öneri apply edilmez |
| AI-12 | Gemini erişim/timeout/quota hatası | Güvenli kullanıcı mesajı görünür; entry değişmez, secret/traceback sızmaz |
| AI-13 | Türkçe dağınık teknik metin | Gerçekler korunarak profesyonel Türkçe üretilir; olmayan komut/port/sürüm uydurulmaz |
| AI-14 | AI environment doğrulaması | Non-secret ayarlar doğrulanır; API key yalnız “set/missing” olarak kontrol edilir |

Gerçek Gemini smoke testi küçük ve secretsız bir örnekle yapılmalı; kota ve
maliyet Google tarafında ayrıca izlenmelidir. Güvenli environment doğrulama
komutu için
[MAINTENANCE_RUNBOOK.md](MAINTENANCE_RUNBOOK.md#5-gemini-ai-production-yapılandırması)
bölümünü kullanın.

## 4. SMTP, mail queue ve scheduled actions

| ID | Test | Beklenen sonuç |
|---|---|---|
| MAIL-01 | SMTP connection testi | Yeni/rotate edilmiş credential ile başarılı |
| MAIL-02 | Submit e-postası | Doğru supervisor adresine gider |
| MAIL-03 | Revision e-postası | İlgili intern user e-posta adresine gider |
| MAIL-04 | Approve e-postası | İlgili intern user e-posta adresine gider |
| MAIL-05 | `force_send=False` queue | Mail önce queue'ya girer, cron tarafından gönderilir |
| MAIL-06 | Hatalı alıcı/SMTP senaryosu | Hata log/queue'da görülür; Odoo servisi çökmez |
| MAIL-07 | Scheduled Actions | Mail queue ve gerekli core cron'lar aktif çalışır |
| MAIL-08 | Restart sonrası bekleyen mail | Cron tekrar işler; duplicate beklenmedik mail oluşmaz |

Database backup SMTP/app password içerebilir. Test backup'ları da production secret politikasına tabidir.

## 5. QWeb PDF ve company logo

| ID | Test | Beklenen sonuç |
|---|---|---|
| PDF-01 | Internship Program PDF üret | HTTP 500 olmadan PDF oluşur |
| PDF-02 | Cover/student/program alanları | Doğru değerler ve tarih formatı görünür |
| PDF-03 | Yalnız approved daily entry'ler | Draft/submitted/revision kayıtlar PDF'de görünmez |
| PDF-04 | Sayfa numarası/header/footer | wkhtmltopdf 0.12.6 ile doğru render edilir |
| PDF-05 | Uzun açıklamalar | Taşma, kesilme ve üst üste binme olmaz |
| PDF-06 | Türkçe karakterler | Font/encoding sorunu olmadan görünür |
| PDF-07 | “Approved Daily Entries” tekrarı | Mevcut duplicate satır kayıt altına alınır ve ürün kararı verilir |
| PDF-08 | Company logo | Mevcut template logo çağırmadığı için beklenen davranış ürün sahibiyle kararlaştırılır |

## 6. Attachment ve filestore

| ID | Test | Beklenen sonuç |
|---|---|---|
| ATT-01 | Daily entry chatter'a dosya yükle | Upload başarılı; filestore'da yeni dosya oluşur |
| ATT-02 | Yüklenen dosyayı indir | Dosya checksum/içerik bozulmadan iner |
| ATT-03 | Yetkisiz user attachment URL'sini açar | Erişim reddedilir |
| ATT-04 | Restore edilen eski attachment | İndirme başarılıdır; missing filestore hatası yoktur |
| ATT-05 | Company logo upload/display | Backend ve ilgili standard layout alanlarında görünür |
| ATT-06 | Odoo restart sonrası attachment | Dosya erişilebilir kalır |

## 7. `ardaapp`

| ID | Test | Beklenen sonuç |
|---|---|---|
| ARD-01 | Order header oluşturma | Kayıt başarılıdır |
| ARD-02 | Order line ekleme/güncelleme/silme | Header ilişkisi ve toplamlar doğru kalır |
| ARD-03 | Mail/chatter davranışı | Mesaj/activity fonksiyonları hatasızdır |
| ARD-04 | Yetkisiz kullanıcı | ACL tarafından beklenen şekilde sınırlandırılır |

## 8. `sales_app`

| ID | Test | Beklenen sonuç |
|---|---|---|
| SAL-01 | Sales header oluşturma | Sequence ile beklenen name oluşur |
| SAL-02 | Product tabanlı line ekleme | Product ilişkisi ve hesaplamalar doğru olur |
| SAL-03 | Header/line update ve delete | İlişkiler tutarlı kalır |
| SAL-04 | Chatter/activity | `mail` entegrasyonu hatasızdır |
| SAL-05 | Sequence restore kontrolü | Yeni kayıt mevcut numarayı tekrar kullanmaz |

## 9. `course_student_management`

| ID | Test | Beklenen sonuç |
|---|---|---|
| CRS-01 | Course CRUD | Course kayıtları oluşturulur/güncellenir/silinir |
| CRS-02 | Student CRUD | E-posta normalizasyonu ve alanlar doğru çalışır |
| CRS-03 | Session oluşturma | Course/session ilişkisi doğru kurulur |
| CRS-04 | İlişkili kayıt silme | `ondelete` davranışı veri kaybı beklentisiyle uyumludur |
| CRS-05 | ACL testi | Yetkili/yetkisiz user davranışı beklenen sonuçtadır |

## 10. Production smoke test ve kabul

Cutover sonrası en az:

1. HTTPS login
2. Mevcut student/program/entry okuma
3. Yeni daily entry oluşturma
4. Submit
5. Revision Request
6. Tekrar submit
7. Approve
8. Mail queue gönderimi
9. PDF oluşturma
10. Eski ve yeni attachment indirme
11. Nginx websocket health
12. Backup service manuel test
13. Gemini AI Assistant güvenlik ve apply smoke testi
14. MuK tema/app bar/chatter/dialog görünüm kontrolü
15. Internship uygulama ikonunun doğru yüklenmesi
16. Off-site backup timer ve son başarılı upload logu
17. Certbot renewal timer durumu

uygulanmalıdır. Frontend/theme/logo değişikliğinde browser hard refresh ve
asset cache kontrolü yapılmalıdır. Kritik bir hata halinde yeni yazma
işlemleri durdurulmalı ve
[MAINTENANCE_RUNBOOK.md](MAINTENANCE_RUNBOOK.md#11-conservative-rollback)
rollback prosedürü izlenmelidir.
