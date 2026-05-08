# Wave 022 — ANSI/VT Terminal Emulation and Render Correctness

Status: done
Owner: Codex
Priority: P1
Depends on: wave_021_interactive_shell_session_architecture.md

## Goal

TRUBA login banner, kutulu duyurular, cursor hareketleri ve terminal redraw davranışlarını daha doğru gösterebilmek için ANSI/VT terminal emülasyon katmanı eklemek ve render doğruluğunu yükseltmek.

## Why This Wave Exists

Wave 020 ve 021 sonrası bile yalnızca düz text append yaklaşımı kullanılıyorsa:
- box drawing ekranları bozulabilir,
- `\r` ve cursor hareketleri yanlış görünür,
- clear/redraw yapan terminal çıktıları dağılır,
- `dialog/whiptail` benzeri ekranlar okunaksız olabilir.

Bu yüzden ham shell çıktısını terminal protokolüne göre yorumlayan bir emülasyon katmanı gerekir.

## Scope

In scope:
- ham shell çıktı akışını ANSI/VT yorumlayan bir terminal emülatörüne bağlamak
- `pyte` benzeri bir lightweight terminal emulation çözümü değerlendirmek ve gerekirse eklemek
- mevcut sanitize/append mantığını ana render yolu olmaktan çıkarmak
- emulator screen buffer'dan UI render üretmek
- carriage return, cursor move, clear screen/line gibi temel terminal davranışlarını doğru ele almak
- TRUBA login banner ve kutulu duyuru ekranını önceki wave'lere göre daha doğru göstermek
- gerekli bağımlılık/dokümantasyon güncellemelerini yapmak

Out of scope:
- PuTTY ile yüzde yüz birebir emülasyon
- tüm özel terminal kontrol dizilerinin eksiksiz desteği
- mouse reporting / advanced terminal modes
- tüm ncurses uygulamalarında kusursuz parity garantisi
- shell architecture'ı yeniden yazmak

## Target Files

Primary targets:
- `src/truba_gui/ssh/client.py`
- `src/truba_gui/ui/widgets/login_widget.py`

Secondary targets only if required:
- `src/truba_gui/ui/widgets/terminal_console.py`
- `src/truba_gui/services/terminal_emulator.py`
- `src/truba_gui/requirements.txt`
- root `requirements.txt`
- `tests/`
- `README.md` veya ilgili kullanıcı dökümü

## Non-Negotiable Rules

1. Ham terminal çıktısı körlemesine sanitize edilip düz yazıya çevrilmemelidir.
2. Emülasyon katmanı küçük ve izole olmalıdır.
3. UI tarafı ile emulator state birbirine aşırı sıkı bağlanmamalıdır.
4. Yeni dependency eklenirse minimum, güvenli ve gerekçeli olmalıdır.
5. Bu wave terminal doğruluğunu artırmalı; gereksiz ürün kapsamı eklememelidir.

## Required Architecture Changes

### A. Emulator Layer

Ham shell stream -> emulator -> renderable screen buffer zinciri kurulmalıdır.

### B. Render Strategy

Widget tarafı:
- screen buffer'ı satır satır çizebilmeli,
- cursor / redraw mantığını bozmayacak şekilde güncellenmeli,
- alternate screen veya clear screen sonrası artık dağınık görüntü oluşturmamalı.

### C. Compatibility Guardrails

Aşağıdaki durumlar güvenli şekilde ele alınmalıdır:
- emulator bağımlılığı yoksa hata yüzeyi
- shell kapanması
- kısmi veya bölünmüş output chunk'ları
- Windows font / unicode box drawing fallback riskleri

## Tasks

- [x] mevcut sanitize/append yolunu analiz et ve ana render yolundan çıkar
- [x] bir ANSI/VT emulation çözümü seç (`pyte` veya eşdeğer lightweight yaklaşım)
- [x] emulator katmanını izole bir helper/service olarak ekle
- [x] shell output chunk'larını emulator'a besle
- [x] emulator screen buffer'dan UI render üret
- [x] carriage return / clear / cursor movement gibi temel davranışları doğrula
- [x] login banner ve kutulu duyuru görünümünü test et
- [x] gerekiyorsa dependency ve dökümantasyonu güncelle
- [x] emülatör yoksa veya hata olursa kontrollü fallback davranışı belirle

## Validation

- [x] TRUBA login banner önceki wave'lere göre anlamlı biçimde daha düzgün görünüyor
- [x] kutulu duyuru ekranı dağılmadan veya ciddi hizasızlık olmadan okunabiliyor
- [x] prompt ve komut çıktıları cursor davranışı bozulmadan ilerliyor
- [x] `\r` kullanan veya satır üstüne yazan çıktıların görünümü iyileşmiş
- [x] emulator entegrasyonu disconnect/reconnect akışını bozmuyor
- [x] yeni dependency eklenmişse kurulum ve import doğrulanmış
- [x] fallback/error handling kullanıcıyı kilitlemiyor

## Done Criteria

This wave is done only when:

1. ANSI/VT yorumlama katmanı uygulamaya eklenmiştir.
2. Login banner ve terminal redraw davranışları belirgin biçimde iyileşmiştir.
3. Mevcut shell akışı bozulmadan render doğruluğu artırılmıştır.
4. Gerekli dependency ve dokümantasyon güncellenmiştir.
5. Terminal deneyimi artık düz log kutusundan anlamlı biçimde daha üst seviyededir.

## Possible Blockers

- Seçilen emulator kütüphanesinin Windows/PySide entegrasyon sorunları
- box drawing karakterlerinde font/fallback farklılıkları
- chunked shell output'un emulator'a doğru beslenmesinde edge-case'ler
- çalışan build ile repo kaynaklarının birebir eşleşmemesi

## On Completion

- bu wave'i `waves/done/` içine taşı
- `ACTIVE_WAVE.md` ve gerekiyorsa `CURRENT_WAVE.md` güncelle
- sonraki wave gerekiyorsa gerçek terminal UX polish / key handling / advanced shortcuts olarak planla
