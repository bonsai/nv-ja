---
name: nv-ja
description: NVIDIA build.nvidia.com（無料クラウド / NVCF）で日本語 STT/TTS を回す薄い CLI（nv-ja）。ja で使えるのは STT=ai-whisper-large-v3、TTS=ai-magpie-tts-multilingual の 2 本だけ（他は ja 非対応、実測済み）。GPU 不要、gRPC で grpc.nvcf.nvidia.com に繋ぐ。「NVIDIA で日本語音声」「nv-ja」「build.nvidia.com で STT/TTS」「NVCF」「whisper-large-v3」「magpie tts」「無料で日本語 TTS」「NVIDIA の音声モデルどれ」で発動。Deepgram 版は deepgram-ja、日本語 TTS のローカル系は tts-skill 系が担う。
---

# nv-ja — NVIDIA 無料クラウドで日本語 STT/TTS

build.nvidia.com の無料枠（NVCF）を gRPC で叩く。**GPU 不要。**

- STT: `ai-whisper-large-v3`（`language_code=ja`）
- TTS: `ai-magpie-tts-multilingual`（`language_code=ja-JP`、既定声）

## なぜこの 2 本か（実測）

| 種別 | モデル | ja |
|---|---|---|
| STT | `ai-whisper-large-v3` | ○ 逆変換で完全一致 |
| STT | `ai-canary-1b-asr` | × ja コードは通るが EU 用 → 崩れる |
| STT | `ai-parakeet-1_1b-rnnt-multilingual-asr` | × EU 25 言語のみ |
| STT | `ai-parakeet-ctc-0_6b` / `ai-parakeet-ctc-1_1b` | × `Unavailable model requested: language_code=ja` |
| STT | `ai-nemotron-asr-streaming` | × 同上 |
| STT | `ai-conformer-ctc-asr` | × ja 非対象 |
| TTS | `ai-magpie-tts-multilingual` | ○ 逆変換で完全一致 |
| TTS | `ai-chatterbox-multilingual-tts` | × 「マラはいいのですね」まで崩壊 |

## 使い方

```bash
export PATH="$HOME/.skills/nv-ja/bin:$PATH"

nv-ja key                     # key 検証 + function-id 解決（NVCF から都度取得、7 日キャッシュ）
nv-ja models                  # audio 系 ACTIVE function 一覧
nv-ja asr in.mp3              # 文字起こし（mp3/wav/m4a 等は内部で ffmpeg 16k mono に変換）
nv-ja asr a.mp3 b.mp3 -o out.txt
nv-ja asr in.mp3 --json       # transcript（whisper NIM は word 時刻を返さない）
nv-ja asr in.mp3 --lang ja-JP --func ai-whisper-large-v3
nv-ja tts "こんにちは。" -o out.mp3
nv-ja tts script.txt -o out.mp3          # ファイル / - で stdin
nv-ja tts "テスト" --voice Magpie-Multilingual.EN-US.Aria   # 声の上書き
```

初回実行時に `~/.skills/nv-ja/.venv` を作り `nvidia-riva-client` を入れる（約 53MB、以降は再利用）。

## 前提

- `NVIDIA_API_KEY`（build.nvidia.com の personal key）。env に無ければ `powershell.exe` 経由で
  Windows ユーザー ENV（`HKCU:\Environment`）から読む。**repo に key を置かない。**
- 関数 ID はリリースごとに回るため `state/function-ids.json` に 7 日キャッシュし、
  期限切れ・未ヒット時に NVCF `/v2/nvcf/functions` から引き直す（ハードコードしない）。

## 既知の制約（実測）

- **無料枠のレート制限が厳しい**: 連投 15 回程度で `RESOURCE_EXHAUSTED: exceeded rate limit`。
  `NV_RETRY`（既定 3）で 15s/30s/45s のバックオフ再試行する。クレジット数の正確な値は未確認。
- **ja のサブボイス名が未確定**: `Magpie-Multilingual.JA-JP.*` は "subvoice requested not found"。
  既定声のみ確認済み。`--voice` は en など他言語の声なら通る。
- whisper NIM は confidence / word 時刻を返さない。
- セルフホスト（NIM コンテナ）は GPU が必要。本 skill はクラウド専用。

## Deepgram との使い分け

STT 精度は Deepgram `nova-3` と同等（どちらも round-trip 一致）。Deepgram は ja の声を 5 種から選べ、
レート制限も緩いが有料。**少量・無料優先 → nv-ja、常用・声の選択が必要 → deepgram-ja。**
