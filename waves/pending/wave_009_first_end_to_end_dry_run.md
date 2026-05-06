# Wave 009 — First End-to-End Dry Run

Status: proposed
Owner: Codex
Priority: P0

## Goal

Sistemi küçük bir gerçek görev üzerinde Architect → Builder → Tester döngüsüyle uçtan uca çalıştırmak.

## Why This Wave Exists

Ayrı ayrı parçaların var olması yeterli değildir. Gerçek değer, sistemin küçük ama gerçek bir task üzerinde state, prompt, model çağrısı, rapor yazımı ve role transition zincirini tutarlı şekilde tamamlamasıyla kanıtlanır. Bu wave, sistemin ilk gerçek operasyonel provasını yapar.

## Scope

In scope:
- küçük ve güvenli bir gerçek task seçmek
- Architect'in task üretmesi
- Builder'ın task'ı uygulaması
- Tester'ın task'ı doğrulaması
- PASS / FAIL / BLOCKED akışını gerçek çalıştırmak
- state güncellemelerini doğrulamak
- rapor oluşumunu doğrulamak

Out of scope:
- büyük refactor
- çok adımlı feature seti
- MCP tool orchestration
- production hardening
- paralel task çalıştırma

## Target Files

Primary targets:
- `TASKS.md`
- `CURRENT_WAVE.md`
- `ACTIVE_WAVE.md`
- `agent_state.json`
- `reports/BUILD_REPORT.md`
- `reports/TEST_REPORT.md`
- `reports/WAVE_REPORT.md`
- `runner/runner.py`

Secondary targets only if required:
- `tests/`
- `scripts/smoke_test.py`
- `scripts/check_i18n.py`

## Non-Negotiable Rules

1. Dry run için seçilen task küçük ve düşük riskli olmalıdır.
2. Bu wave sırasında sistem mimarisini genişletmeye çalışılmamalıdır.
3. PASS / FAIL / BLOCKED kararları gerçek rapor ve test çıktısına dayanmalıdır.
4. State dosyası her adım sonunda tutarlı kalmalıdır.
5. Dry run başarısız olursa aynı wave içinde sorun görünür hale getirilmelidir; gizlenmemelidir.

## Required Architecture Changes

### A. Minimal Real Task Selection

Test için seçilecek task:
- küçük
- net acceptance criteria içeren
- allowed files sınırı dar
- mevcut test veya smoke komutlarıyla doğrulanabilir
olmalıdır.

### B. Full Loop Verification

Aşağıdaki zincir tek bir denemede gözlemlenebilmelidir:
- Architect task seçer/yazar
- Builder implement eder
- Builder rapor üretir
- Tester doğrular
- Tester rapor üretir
- Runner state günceller

### C. Recovery Signal Visibility

Başarısızlık durumunda hangi aşamada bozulduğu rapor ve loglardan anlaşılmalıdır.

## Tasks

- [ ] küçük bir gerçek task seç
- [ ] task için acceptance criteria ve allowed files sınırını netleştir
- [ ] Architect akışıyla `TASKS.md` güncelle
- [ ] Builder çalıştır ve `BUILD_REPORT.md` oluştur
- [ ] Tester çalıştır ve `TEST_REPORT.md` oluştur
- [ ] `agent_state.json` içindeki geçişleri doğrula
- [ ] PASS / FAIL / BLOCKED sonuçlarından en az birini doğrula
- [ ] `reports/WAVE_REPORT.md` içine dry run sonucu özetini yaz

## Validation

- [ ] seçilen task gerçekten küçük ve izole
- [ ] Architect çıktısı task oluşturuyor
- [ ] Builder raporu oluşuyor
- [ ] Tester raporu oluşuyor
- [ ] state güncellemesi beklenen role transition ile uyumlu
- [ ] sistem kapanıp tekrar açıldığında state okunabiliyor
- [ ] dry run sonucu raporda özetlenmiş

## Done Criteria

This wave is done only when:

1. En az bir gerçek task Architect → Builder → Tester zincirinden geçmiştir.
2. Rapor dosyaları oluşmuş ve okunabilir durumdadır.
3. `agent_state.json` beklenen geçişleri doğru yansıtmaktadır.
4. Başarı veya başarısızlık durumu açıkça gözlemlenebilmektedir.

## Possible Blockers

- çok büyük veya belirsiz bir task seçilmesi
- Builder çıktısının parse edilememesi
- Tester sonucunun standarda uymaması
- state güncellemelerinde tutarsızlık

## On Completion

- bu wave'i `waves/done/` içine taşı
- bir sonraki aktif wave olarak `wave_010_mcp_bridge_foundation.md` ayarla
