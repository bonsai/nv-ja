#!/usr/bin/env python3
"""nv_ja.py — nv-ja の実体。bash ラッパーが venv の python でこれを呼ぶ。

設定は env（conf/nv-ja.env → bash が export）から読む。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

import riva.client

ETC = os.environ


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def die(msg: str) -> "NoReturn":  # noqa: F821
    print(f"nv-ja: {msg}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------- function ids
def fetch_functions() -> list[dict]:
    url = "https://api.nvcf.nvidia.com/v2/nvcf/functions?visibility=public,authorized"
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + env("NV_KEY")})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r).get("functions", [])
    except Exception as e:  # noqa: BLE001
        die(f"NVCF functions 取得失敗: {type(e).__name__} {e}")


def cache_path() -> str:
    state = env("NV_STATE_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state"))
    os.makedirs(state, exist_ok=True)
    return os.path.join(state, "function-ids.json")


def read_cache() -> dict:
    try:
        with open(cache_path(), encoding="utf-8") as f:
            blob = json.load(f)
    except Exception:  # noqa: BLE001
        return {}
    ttl = float(env("NV_FUNC_CACHE_DAYS", "7")) * 86400
    if time.time() - blob.get("ts", 0) > ttl:
        return {}
    return blob.get("ids", {})


def write_cache(ids: dict) -> None:
    try:
        with open(cache_path(), "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "ids": ids}, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def resolve_function(name: str, refresh: bool = False) -> str:
    ids = {} if refresh else read_cache()
    if name in ids:
        return ids[name]
    funcs = fetch_functions()
    hit = next((f for f in funcs if f.get("name") == name and f.get("status") == "ACTIVE"), None)
    if not hit:
        cands = sorted({f["name"] for f in funcs if f.get("status") == "ACTIVE" and
                        any(k in f["name"] for k in ("asr", "tts", "whisper", "magpie", "parakeet", "canary", "conformer"))})
        die(f"ACTIVE な function が無い: {name}\n  audio 系の候補: {', '.join(cands)}")
    ids = read_cache() or {}
    ids[name] = hit["id"]
    write_cache(ids)
    return hit["id"]


# --------------------------------------------------------------------- riva io
def auth_for(func_id: str) -> riva.client.Auth:
    return riva.client.Auth(
        uri=env("NV_GRPC", "grpc.nvcf.nvidia.com:443"),
        use_ssl=True,
        metadata_args=[["function-id", func_id], ["authorization", "Bearer " + env("NV_KEY")]],
    )


RETRYABLE = ("RESOURCE_EXHAUSTED", "UNAVAILABLE", "failed to establish link to worker")


def with_retry(fn, what: str):
    n = int(env("NV_RETRY", "3"))
    for i in range(n + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            text = f"{type(e).__name__} {e}"
            if i >= n or not any(k in text for k in RETRYABLE):
                die(f"{what} 失敗: {text.splitlines()[2] if len(text.splitlines()) > 2 else text}")
            wait = 15 * (i + 1)
            print(f"nv-ja: rate limit 等で待機 {wait}s（{i + 1}/{n}）", file=sys.stderr)
            time.sleep(wait)


def to_pcm16000(path: str) -> bytes:
    """任意の音声 → 16kHz mono s16le raw。"""
    if path.endswith((".pcm", ".raw")) and env("NV_ASR_PCM_AS_IS") == "1":
        with open(path, "rb") as f:
            return f.read()
    sr = env("NV_ASR_SR", "16000")
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "a.pcm")
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-ar", sr, "-ac", "1", "-f", "s16le", out]
        subprocess.run(cmd, check=True)
        with open(out, "rb") as f:
            return f.read()


def write_audio(pcm: bytes, out: str, sr: str) -> None:
    """TTS の raw PCM を mp3（ffmpeg が無ければ wav）に。"""
    ext = os.path.splitext(out)[1].lower()
    with tempfile.TemporaryDirectory() as td:
        raw = os.path.join(td, "t.pcm")
        with open(raw, "wb") as f:
            f.write(pcm)
        if ext in (".wav", ".pcm"):
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", sr, "-ac", "1",
                            "-i", raw, out], check=True)
        else:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", sr, "-ac", "1",
                            "-i", raw, "-b:a", "192k", out], check=True)


# ------------------------------------------------------------------- commands
def cmd_asr(argv: list[str]) -> int:
    files, out, as_json = [], "", False
    lang, func_name = env("NV_ASR_LANG", "ja"), env("NV_ASR_FUNC_NAME", "ai-whisper-large-v3")
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-o", "--out"):
            out = argv[i + 1]; i += 2
        elif a in ("--lang", "--language"):
            lang = argv[i + 1]; i += 2
        elif a == "--func":
            func_name = argv[i + 1]; i += 2
        elif a in ("--json", "-j"):
            as_json = True; i += 1
        elif a in ("-h", "--help"):
            print("nv-ja asr <audio...> [-o out.txt] [--json] [--lang L] [--func NAME]"); return 0
        else:
            files.append(a); i += 1
    if not files:
        die("音声ファイルを指定してください（複数可）")

    func_id = resolve_function(func_name)
    auth = auth_for(func_id)
    asr = riva.client.ASRService(auth)
    results = []
    for path in files:
        if not os.path.isfile(path):
            die(f"見つかりません: {path}")
        pcm = to_pcm16000(path)
        cfg = riva.client.RecognitionConfig(
            encoding=riva.client.AudioEncoding.LINEAR_PCM,
            sample_rate_hertz=int(env("NV_ASR_SR", "16000")),
            language_code=lang,
            max_alternatives=1,
            enable_automatic_punctuation=True,
            enable_word_time_offsets=True,
            audio_channel_count=1,
        )
        resp = with_retry(lambda: asr.offline_recognize(pcm, cfg), f"ASR {os.path.basename(path)}")
        best = resp.results[0].alternatives[0] if resp.results else None
        if best is None:
            die("ASR が空の応答を返しました")
        results.append((path, best))
        if not as_json:
            text = best.transcript
            line = f"{os.path.basename(path)}\t{text}" if len(files) > 1 else text
            print(line)
            if out:
                with open(out, "a", encoding="utf-8") as f:
                    f.write(line + "\n")

    if as_json:
        blob = []
        for p, b in results:
            row = {"file": p, "transcript": b.transcript}
            if getattr(b, "confidence", 0):
                row["confidence"] = b.confidence
            words = [{"word": w.word, "start": w.start_time, "end": w.end_time} for w in b.words]
            if words:  # whisper NIM は word 時刻を返さない（空になる）
                row["words"] = words
            blob.append(row)
        text = json.dumps(blob[0] if len(blob) == 1 else blob, ensure_ascii=False, indent=2)
        print(text)
        if out:
            with open(out, "w", encoding="utf-8") as f:
                f.write(text + "\n")
    if out:
        print(f"nv-ja: -> {out}", file=sys.stderr)
    return 0


def cmd_tts(argv: list[str]) -> int:
    text, out = "", ""
    voice, lang = env("NV_TTS_VOICE", ""), env("NV_TTS_LANG", "ja-JP")
    func_name = env("NV_TTS_FUNC_NAME", "ai-magpie-tts-multilingual")
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-o", "--out"):
            out = argv[i + 1]; i += 2
        elif a == "--voice":
            voice = argv[i + 1]; i += 2
        elif a in ("--lang", "--language"):
            lang = argv[i + 1]; i += 2
        elif a == "--func":
            func_name = argv[i + 1]; i += 2
        elif a in ("-h", "--help"):
            print("nv-ja tts <text|file|-> [-o out.mp3] [--voice V] [--lang L] [--func NAME]"); return 0
        elif a == "-":
            text = "-"; i += 1
        elif already_text := (text != ""):
            die("テキストは 1 つだけ")
        else:
            text = a; i += 1
    if text == "-":
        text = sys.stdin.read()
    elif text and os.path.isfile(text):
        with open(text, encoding="utf-8") as f:
            text = f.read()
    if not text.strip():
        die("テキスト（またはファイル / - で stdin）を指定してください")

    func_id = resolve_function(func_name)
    tts = riva.client.SpeechSynthesisService(auth_for(func_id))
    sr = int(env("NV_TTS_SR", "22050"))
    kw = {"sample_rate_hz": sr, "encoding": riva.client.AudioEncoding.LINEAR_PCM}
    if lang:
        kw["language_code"] = lang
    if voice:
        kw["voice_name"] = voice
    resp = with_retry(lambda: tts.synthesize(text, **kw), "TTS synthesize")
    if not resp.audio:
        die("TTS が空の音声を返しました")

    if not out:
        ext = ".mp3"
        out = f"nv-ja-{time.strftime('%Y%m%d-%H%M%S')}{ext}"
    write_audio(resp.audio, out, str(sr))
    print(f"nv-ja: {out} ({os.path.getsize(out)} bytes, {func_name} {lang} {voice or 'default-voice'})")
    return 0


def cmd_models(argv: list[str]) -> int:
    show_all = "--all" in argv
    funcs = fetch_functions()
    keys = ("asr", "tts", "whisper", "magpie", "parakeet", "canary", "conformer", "chatterbox", "riva")
    rows = [f for f in funcs if f.get("status") == "ACTIVE" and
            (show_all or any(k in f["name"] for k in keys))]
    for f in sorted(rows, key=lambda x: x["name"]):
        print(f"{f['status']:8} {f['name']}")
    ja = env("NV_ASR_FUNC_NAME", ""), env("NV_TTS_FUNC_NAME", "")
    print(f"\nja で使うのは: {ja[0]} (STT) / {ja[1]} (TTS)")
    return 0


def cmd_key(argv: list[str]) -> int:
    funcs = fetch_functions()
    act = [f for f in funcs if f.get("status") == "ACTIVE"]
    print(f"key OK: ACTIVE functions {len(act)} / total {len(funcs)}")
    for name in (env("NV_ASR_FUNC_NAME", "ai-whisper-large-v3"), env("NV_TTS_FUNC_NAME", "ai-magpie-tts-multilingual")):
        try:
            print(f"  {name} -> {resolve_function(name)}")
        except SystemExit:
            raise
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        die("サブコマンド: asr | tts | models | key")
    cmd, rest = argv[0], argv[1:]
    table = {"asr": cmd_asr, "stt": cmd_asr, "tts": cmd_tts, "speak": cmd_tts,
             "models": cmd_models, "key": cmd_key}
    if cmd not in table:
        die(f"未知のサブコマンド: {cmd}")
    return table[cmd](rest)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
