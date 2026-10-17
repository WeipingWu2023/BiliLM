# BiliLM Phase 1

## Environment
Windows 11 / Python 3.12.10 / Node 24.14.1 / npm 11.11 / FFmpeg available. Empty checkout. Initial CIM inspection unavailable; stdlib diagnostics confirmed 16 logical CPUs and 31.7 GiB RAM. GPU unconfirmed, CPU int8 default. First model download needs internet. Hardware diagnostics: `python scripts/doctor.py`.

## Research and decisions
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper): CTranslate2, CPU int8, segment timestamps, VAD. Selected as requested; tiny for smoke tests, small default, medium/large require more RAM/time.
- [OpenAI Whisper](https://github.com/openai/whisper): reference implementation, heavier PyTorch runtime; not selected.
- [whisper.cpp](https://github.com/ggml-org/whisper.cpp): capable native CPU alternative, different runtime; not needed for Phase 1.
- [yt-dlp](https://github.com/yt-dlp/yt-dlp): broad extractor library but Bilibili subtitle/access behavior varies. Use a small isolated Bilibili HTTP adapter; fail on access restrictions, no browser cookie scraping, no CAPTCHA/DRM bypass.
- Agent Reach doctor + GitHub CLI attempted; shell network unavailable during initial inspection. Web primary sources read through web search. Recheck live ingestion separately; mock tests do not prove platform availability.

## Architecture
Browser → Next.js same-origin `/api` proxy → FastAPI → SQLite (WAL).
Separate single worker claims queued jobs with SQLite transaction. Running jobs recovered on worker restart; never run multiple workers. Video key `BV:p`, local file key SHA256. Unique key and active-job transaction deduplicate imports. Metadata, subtitle ingestion, ASR, deterministic cleaning and optional LLM reasoning are separate modules. Original segments inserted once; editable readable text stored separately with edit revision for conflict protection. No AI cleaning in Phase 1; paragraph/punctuation formatting preserves source words. AI assistant uses local transcript search with timestamps; optional OpenAI-compatible provider explicitly configured by environment.

## Structure
`backend/app`: API, database, ingestion, transcript, ASR, worker, reasoning.
`backend/tests`: parser, transcript, cache, restart/retry and API checks.
`frontend/app`: Chinese import/library/workspace UI.
`scripts`: hardware diagnostics and live smoke check.
`data`: ignored SQLite, authorized uploads, audio, model cache.

## Milestones
1. Validate URL/BV/short links, SQLite library/cache and queue.
2. Public metadata + permitted subtitles; accessible audio → FFmpeg → faster-whisper; local fallback.
3. Three panels, chapters/timeline, readable editor, search, copy and TXT/SRT/Markdown exports, assistant extension.
4. Restart recovery, retries, meaningful automated checks, production build and live URL smoke.

## Risks and boundaries
Platform 403/412/login-only/removed/paid videos may fail; report code and local upload option without circumvention. Public player subtitle endpoint may omit tracks without authorization. Short redirects and CDN URLs allowlisted to prevent SSRF. Multi-part URLs preserve `p`; only selected part imported. Network timeouts and download/upload byte limits prevent unbounded transfers. CPU ASR may be slow and hallucinate; timestamps and provenance remain visible. Model download/offline availability cannot be assumed. Single worker restarts retry interrupted processing; original committed transcript never overwritten. Localhost-only service, same-origin proxy and API origin checks; do not expose to LAN. Local uploads must be authorized. Optional LLM sends text externally only when configured and invoked. No Phase 2/3 features.

## Acceptance criteria
- Supported public URL/BV/short link resolves selected part metadata, nonempty timestamped transcript and readable text saved in library.
- Subtitle-first path and real CPU ASR fallback individually verified (fixtures alone insufficient for live acceptance).
- Reimport same video/part hits cache; concurrent imports create one active job.
- Original retained after readable edits; stale edits rejected; SRT always original timestamped text.
- Search/copy/TXT/MD/SRT functional, Chinese responsive workspace with empty/loading/error states.
- Restricted/unavailable media produces actionable failure; retry and authorized local upload work.
- Queued jobs survive process restart; interrupted running job recovered; cache preserved.
- Automated tests and Next production build pass; Windows startup starts both services + one worker and reports dependency failures.
- Live smoke records source ID, title, provenance, segment count and exports. If network/platform/model unavailable, explicitly report unmet live acceptance rather than claiming completion.
