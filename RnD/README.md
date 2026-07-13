# Research & Development (RnD)

This directory contains research findings, competitive analyses, technical investigations, and experimental documentation for VegaPunkR.

## Contents

### Competitive Analysis
- **[competitive-analysis-2026.md](./competitive-analysis-2026.md)** - Deep research comparing VegaPunkR to industry-leading trading engines (QuantConnect LEAN, Nautilus Trader, Freqtrade, etc.)
  - 106-agent analysis with adversarial verification
  - What we're doing well vs industry best practices
  - Critical gaps and improvement recommendations
  - Prioritized action items

## Purpose

This directory is for:
- ✅ Industry research and competitive analysis
- ✅ Technical investigations and POCs (proof of concepts)
- ✅ Architecture decision records (ADRs)
- ✅ Performance benchmarks and optimization research
- ✅ Experimental features and prototypes
- ✅ Third-party integration research

**Not for:**
- ❌ User-facing documentation (use `docs/` instead)
- ❌ API documentation (use `docs/` instead)
- ❌ Setup guides (use `docs/` instead)

## Organization

Research documents should follow this naming convention:
- `competitive-analysis-YYYY.md` - Industry competitive analysis
- `adr-NNN-title.md` - Architecture Decision Records
- `benchmark-feature-name.md` - Performance benchmarks
- `research-topic-name.md` - Technical research
- `poc-feature-name/` - Proof of concept implementations

## Contributing Research

When adding research:
1. Include date and methodology
2. Cite sources (links, repos, papers)
3. Document verification process if applicable
4. Add summary to this README

## Archive

Older research should be moved to `RnD/archive/YYYY/` to keep the directory focused on current/active investigations.

---

**Last Updated:** July 11, 2026
