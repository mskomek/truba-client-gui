# Wave 010 — MCP Bridge Foundation

Status: proposed
Owner: Codex
Priority: P1

## Goal

Codex ile yerel workflow dosyaları ve raporları arasında güvenli bir read-only MCP köprüsü kurmak.

## Why This Wave Exists

Sistem MCP olmadan da çalışabilir, ancak Codex'in state, aktif task ve raporları doğrudan standart tool çağrılarıyla okuyabilmesi orchestration temizliği sağlar. İlk adım olarak read-only bir MCP bridge kurmak en güvenli yaklaşımdır; önce gözlem sağlanır, sonra eylem tool'ları eklenir.

## Scope

In scope:
- temel MCP server iskeleti
- read-only tool tanımları
- state ve rapor okuma tool'ları
- aktif task ve aktif wave okuma tool'ları
- Codex tarafında MCP bağlantı tanımını hazırlamak
- localhost ve güvenli kullanım sınırlarını belirlemek

Out of scope:
- Builder çalıştıran MCP tool'ları
- Tester çalıştıran MCP tool'ları
- write-capable state değişiklik tool'ları
- uzak ağ erişimi
- production deployment

## Target Files

Primary targets:
- `.codex/config.toml`
- `runner/mcp_server.py`
- `AGENTS.md`
- `MASTER_CONTEXT_ACTIVE.md`
- `SESSION_RULES.md`
- `agent_state.json`
- `TASKS.md`
- `CURRENT_WAVE.md`
- `reports/BUILD_REPORT.md`
- `reports/TEST_REPORT.md`

Secondary targets only if required:
- `README_AGENT_WORKFLOW.md`
- `runner/`
- `waves/`

## Non-Negotiable Rules

1. İlk MCP bridge read-only olmalıdır.
2. MCP server yalnızca localhost üzerinde çalışmalıdır.
3. Shell injection riski oluşturacak dinamik komut çalıştırma eklenmemelidir.
4. Tool'lar açık, küçük ve tek amaçlı olmalıdır.
5. Builder/Tester tetikleme bu wave içinde yapılmamalıdır.

## Required Architecture Changes

### A. MCP Read-Only Surface

Aşağıdaki tool yüzeyi sağlanmalıdır:
- `get_state()`
- `get_active_task()`
- `get_current_wave()`
- `read_build_report()`
- `read_test_report()`

### B. Codex Configuration Hook

Codex tarafı MCP server'ı görebilecek şekilde yapılandırılmalıdır:
- kullanıcı veya proje bazlı config
- güvenli local command tanımı
- gerekli env açıklamaları

### C. Trust Boundary Definition

MCP bridge'in neyi yapabildiği ve neyi yapamadığı açıkça belgelenmelidir.

## Tasks

- [ ] temel `runner/mcp_server.py` iskeletini oluştur
- [ ] read-only tool fonksiyonlarını tanımla
- [ ] `agent_state.json` ve aktif task/wave okuma mantığını ekle
- [ ] build ve test report okuma araçlarını ekle
- [ ] `.codex/config.toml` için örnek MCP bağlantı tanımını yaz
- [ ] localhost-only ve güvenlik sınırlarını dokümante et
- [ ] MCP bridge davranışını `AGENTS.md` ve ilgili dokümanlara yansıt

## Validation

- [ ] MCP server lokal olarak ayağa kalkabiliyor
- [ ] en az bir state okuma tool'u çalışıyor
- [ ] en az bir report okuma tool'u çalışıyor
- [ ] aktif wave veya aktif task okunabiliyor
- [ ] Codex config örneği geçerli ve anlaşılır
- [ ] bridge'in read-only sınırı açıkça belgelenmiş

## Done Criteria

This wave is done only when:

1. Read-only MCP server iskeleti oluşturulmuştur.
2. State, task, wave ve rapor okuma için temel tool'lar vardır.
3. Codex tarafı MCP bridge'i yapılandırabilecek duruma gelmiştir.
4. Güvenlik ve trust boundary açıkça dokümante edilmiştir.

## Possible Blockers

- MCP server kütüphane seçiminde kararsızlık
- config yolunun proje ve kullanıcı düzeyinde netleşmemesi
- state ve rapor dosyalarının beklenenden farklı biçimde bulunması

## On Completion

- bu wave'i `waves/done/` içine taşı
- bir sonraki aktif wave olarak `wave_011_mcp_builder_tester_tools.md` ayarla
