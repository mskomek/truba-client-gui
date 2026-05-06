# Wave 008 — Codex Architect Flow

Status: proposed
Owner: Codex
Priority: P0

## Goal

Codex'in bu repoda yalnızca Architect olarak davranmasını sağlayan tutarlı çalışma akışını kurmak.

## Why This Wave Exists

Builder ve Tester tarafı hazırlandıktan sonra sistemin doğru çalışması için task üretimi, acceptance criteria yazımı, allowed/forbidden files sınırları ve route kararları tek bir tutarlı Architect akışına bağlanmalıdır. Codex'in implementer gibi davranması yerine scope yöneten, task bölen ve karar veren rolü netleşmelidir.

## Scope

In scope:
- Architect prompt akışını netleştirmek
- Task üretim formatını sabitlemek
- Wave içinden sıradaki en küçük doğrulanabilir task seçimini tanımlamak
- `TASKS.md` güncelleme kurallarını belirlemek
- Route kararlarının standardını oluşturmak
- Architect'in kod yazmama sınırını netleştirmek

Out of scope:
- Builder implementasyon mantığını değiştirmek
- Tester doğrulama mantığını değiştirmek
- MCP server implementasyonu
- Ek runtime tool entegrasyonları

## Target Files

Primary targets:
- `AGENTS.md`
- `TASKS.md`
- `CURRENT_WAVE.md`
- `ACTIVE_WAVE.md`
- `runner/prompts/architect.md`
- `MASTER_CONTEXT_ACTIVE.md`
- `SESSION_RULES.md`

Secondary targets only if required:
- `ARCHITECTURE.md`
- `PHASE_PLAN.md`
- `TESTING.md`

## Non-Negotiable Rules

1. Codex Architect kaynak kod implementasyonu yapmamalıdır.
2. Her yeni task küçük, doğrulanabilir ve geri alınabilir olmalıdır.
3. Her task açık acceptance criteria içermelidir.
4. Her task allowed files ve forbidden files tanımı içermelidir.
5. Architect gelecekteki task'ları başlatmamalı, yalnızca sıradaki task'ı hazırlamalıdır.
6. Scope genişletme gerekiyorsa bu açıkça yazılmalı ve BLOCKED olarak ele alınmalıdır.

## Required Architecture Changes

### A. Architect Role Contract

Codex için net bir rol sözleşmesi tanımlanmalıdır:
- wave'i okur
- aktif task durumunu okur
- sıradaki task'ı seçer
- `TASKS.md` içinde task tanımı yazar
- Builder'a handoff üretir

### B. Task Definition Standard

Task tanımı şu alanları standardize etmelidir:
- task id
- summary
- goal
- dependencies
- allowed files
- forbidden files
- acceptance criteria
- required test commands
- route

### C. Handoff Discipline

Architect çıktısı parse edilebilir ve tutarlı olmalıdır. Handoff formatı Builder tarafından yanlış anlaşılmayacak kadar net olmalıdır.

## Tasks

- [ ] `runner/prompts/architect.md` dosyasını repo gerçeklerine göre sıkılaştır
- [ ] Architect için rol sınırlarını `AGENTS.md` içinde netleştir
- [ ] `TASKS.md` için standart task şablonunu oluştur veya güncelle
- [ ] Wave içinden task seçme kurallarını `CURRENT_WAVE.md` / `ACTIVE_WAVE.md` akışına bağla
- [ ] Architect route kararlarını dokümante et
- [ ] Kod yazmama ve scope genişletmeme kurallarını açıkça yaz
- [ ] Builder ve Tester raporlarını okuyarak sonraki task seçim mantığını tanımla

## Validation

- [ ] Codex promptu okunduğunda yalnızca Architect rolü tarif ediliyor
- [ ] En az bir örnek task tanımı eksiksiz üretilebiliyor
- [ ] Task tanımında allowed/forbidden files alanları yer alıyor
- [ ] Architect çıktısı Builder handoff formatına uyuyor
- [ ] Kod implementasyonu içeren bir Architect çıktısı başarısız kabul ediliyor

## Done Criteria

This wave is done only when:

1. Codex için Architect davranışı net ve tekrarlanabilir hale gelmiştir.
2. `TASKS.md` içinde standart bir task tanım formatı bulunmaktadır.
3. Architect promptu ve rol kuralları bu repo ile uyumlu hale gelmiştir.
4. Bir örnek task üretimi insan müdahalesi olmadan anlaşılır şekilde oluşmaktadır.

## Possible Blockers

- Mevcut `TASKS.md` formatının fazla gevşek olması
- Architect promptunun çok genel kalması
- Repo bağlam dokümanlarının yetersiz detay içermesi

## On Completion

- bu wave'i `waves/done/` içine taşı
- bir sonraki aktif wave olarak `wave_009_first_end_to_end_dry_run.md` ayarla
