# HANDOVER — nv-ja

現在地（2026-09-29）

- 目的: NVIDIA build.nvidia.com の無料枠（NVCF）で日本語 STT/TTS を回す。
- 実体: `bin/nv-ja`（bash: key 解決 + venv bootstrap）, `bin/nv_ja.py`（本体: riva gRPC）, `conf/nv-ja.env`, `state/function-ids.json`（7 日キャッシュ）。
- ja の答え: STT=`ai-whisper-large-v3`、TTS=`ai-magpie-tts-multilingual`。他は ja 非対応（SKILL.md の表は実測）。
- 依存: `nvidia-riva-client` を `.venv` に自動 install（初回 ~14s、53MB）。`NVIDIA_API_KEY` は WSL env と Windows ユーザー ENV（setx, HKCU 確認済み）の両方に登録済み。env 無しでも registry 経由で動くことを実測。
- 検証済み: key/function 解決、asr（mp3 直接→一致）、tts（mp3 出力）、tts→asr round-trip 一致、初回 bootstrap、`--json`、レート制限リトライ、subvoice 指定時のエラー表示。
- 未検証: クレジット数、ja サブボイス名（`Magpie-Multilingual.JA-JP.*` は not found）、`ai-magpie-tts-zeroshot` の ja、長文 TTS。
- 次にやるなら: ja ボイス名の特定（build.nvidia.com の TTS ページ / python-clients の list_voices）、長文分割、`deepgram-ja` と共通の `asr`/`tts` インターフェース化。

## ISSUE_LOG

- 2026-09-29 Windows ENV に NVIDIA_API_KEY を setx 登録。WSL env を空にしても key 解決 + function 解決が通ることを実測。
- 2026-09-29 NVIDIA 音声モデルの ja 対応を総当たり（STT 6 / TTS 2）し、whisper-large-v3 + magpie-tts-multilingual の 2 本に確定。CLI 化して commit/push。
