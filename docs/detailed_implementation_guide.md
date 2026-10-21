# Volume Stabilizer 詳細実装指示書 (Detailed Implementation Guide)

本ドキュメントは、Volume Stabilizer を迷いなく一貫した品質で実装するための、完全なファイルツリー、モジュール責務、関数シグネチャ、ffmpeg コマンドライン、およびタグ操作コードの詳細指示書です。

---

## 1. ファイルツリー構成

```
volume_stabilizer/
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── README.md
├── tests/
│   ├── conftest.py
│   ├── test_analyzer.py
│   ├── test_hasher.py
│   ├── test_processor.py
│   ├── test_tagger.py
│   ├── test_db.py
│   └── test_e2e.py
└── volume_stabilizer/
    ├── __init__.py
    ├── config.py
    ├── core/
    │   ├── __init__.py
    │   ├── analyzer.py       # EBU R128解析・ゲイン計算
    │   ├── backup.py         # 強制再処理時の旧出力バックアップ
    │   ├── hasher.py         # 音声PCMストリームのSHA-256算出
    │   ├── processor.py      # ffmpeg DSP (ゲイン/リミッター/エンコード/バイパス)
    │   ├── scanner.py        # 音源ディレクトリスキャン & コーデック判定
    │   └── tagger.py         # mutagen ID3/GEOB/Serato/BPM/Keyタグ移植
    ├── db/
    │   ├── __init__.py
    │   ├── database.py       # SQLite接続プール・初期化 (WAL)
    │   ├── models.py         # Pydanticモデル / データクラス
    │   └── repository.py     # トラック・ジョブ・解析結果のDBアクセス層
    ├── queue/
    │   ├── __init__.py
    │   └── worker_pool.py    # ProcessPoolExecutorによる並列ジョブ実行管理
    ├── api/
    │   ├── __init__.py
    │   ├── app.py            # FastAPI初期化・ルーター登録
    │   ├── routes.py         # RESTエンドポイント実装
    │   └── websocket.py      # WebSocket接続管理 & イベント配信
    ├── cli/
    │   ├── __init__.py
    │   └── main.py           # vstab CLI コマンド (Click/Typer)
    └── static/
        ├── index.html        # Web UI メイン画面
        ├── css/
        │   └── app.css       # スタイリング (Dark DJテーマ)
        └── js/
            └── app.js        # フロントエンドロジック (Vanilla JS)
```

---

## 2. コアモジュール実装仕様

### 2.1 `volume_stabilizer/core/hasher.py`
メタデータを完全に除外した純粋な音声ストリームのハッシュを計算。

```python
import hashlib
import subprocess
from pathlib import Path

def compute_audio_hash(file_path: Path) -> str:
    """
    ファイルをデコードして固定PCMストリーム (s16le, 2ch, 44100Hz) に変換し、
    そのSHA-256を算出する。タグやヘッダーが変更されても同一音源なら常に同じハッシュを出力。
    """
    cmd = [
        "ffmpeg", "-nostats", "-loglevel", "error",
        "-i", str(file_path),
        "-vn", "-sn", "-dn",
        "-f", "s16le", "-ac", "2", "-ar", "44100",
        "-"
    ]
    hasher = hashlib.sha256()
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        while chunk := proc.stdout.read(65536):
            hasher.update(chunk)
        _, err = proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Audio hash failed for {file_path}: {err.decode('utf-8', errors='ignore')}")
    return hasher.hexdigest()
```

---

### 2.2 `volume_stabilizer/core/analyzer.py`
EBU R128 によるラウドネス解析と、必要ゲイン・リミッター要否の算出。

```python
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

TARGET_LUFS = -10.0
PEAK_CEILING_DBTP = -1.0
MAX_LIMITER_REDUCTION_DB = 3.0
BYPASS_TOLERANCE_LU = 0.5

@dataclass
class LoudnessAnalysis:
    integrated_lufs: float
    true_peak_dbtp: float
    lra_lu: float
    target_gain_db: float
    limiter_required: bool
    limiter_reduction_db: float
    effective_gain_db: float
    bypass_eligible: bool
    warning_code: str  # 'NONE', 'LOUDNESS_UNDER_TARGET', 'HIGH_PEAK'

def analyze_track(file_path: Path, is_mp3: bool) -> LoudnessAnalysis:
    cmd = [
        "ffmpeg", "-nostats",
        "-i", str(file_path),
        "-filter_complex", "ebur128=peak=true",
        "-f", "null", "-"
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stderr = proc.stderr

    # ebur128 summary パース
    i_match = re.search(r"Integrated loudness:\s+I:\s+([-\d.]+)\s+LUFS", stderr)
    tp_match = re.search(r"Peak:\s+True:\s+([-\d.]+)\s+dBFS", stderr)
    lra_match = re.search(r"Loudness range:\s+LRA:\s+([-\d.]+)\s+LU", stderr)

    if not i_match or not tp_match:
        raise ValueError(f"Could not parse ebur128 output for {file_path}")

    i_lufs = float(i_match.group(1))
    tp_dbtp = float(tp_match.group(1))
    lra_lu = float(lra_match.group(1)) if lra_match else 0.0

    raw_gain = TARGET_LUFS - i_lufs
    pred_tp = tp_dbtp + raw_gain

    limiter_required = pred_tp > PEAK_CEILING_DBTP
    limiter_reduction = max(0.0, pred_tp - PEAK_CEILING_DBTP) if limiter_required else 0.0

    warning_code = "NONE"
    effective_gain = raw_gain

    # リミッター上限 3.0 dB の適用
    if limiter_reduction > MAX_LIMITER_REDUCTION_DB:
        # 許容リダクション上限を超えた場合、ゲイン自体を抑制して音質を守る
        excess = limiter_reduction - MAX_LIMITER_REDUCTION_DB
        effective_gain = raw_gain - excess
        limiter_reduction = MAX_LIMITER_REDUCTION_DB
        warning_code = "LOUDNESS_UNDER_TARGET"

    # MP3 無加工バイパス判定:
    # 差分が ±0.5 LU 以内、かつ元の True Peak が -1.0 dBTP 以下
    bypass_eligible = is_mp3 and (abs(raw_gain) <= BYPASS_TOLERANCE_LU) and (tp_dbtp <= PEAK_CEILING_DBTP)

    return LoudnessAnalysis(
        integrated_lufs=i_lufs,
        true_peak_dbtp=tp_dbtp,
        lra_lu=lra_lu,
        target_gain_db=raw_gain,
        limiter_required=limiter_required,
        limiter_reduction_db=limiter_reduction,
        effective_gain_db=effective_gain,
        bypass_eligible=bypass_eligible,
        warning_code=warning_code
    )
```

---

### 2.3 `volume_stabilizer/core/processor.py`
ffmpeg フィルタグラフの構築とエンコード実行。

```python
import subprocess
from pathlib import Path
from .analyzer import LoudnessAnalysis, PEAK_CEILING_DBTP

def process_audio(
    input_path: Path,
    output_path: Path,
    analysis: LoudnessAnalysis,
    output_format: str  # 'mp3' or 'aiff'
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. MP3 無加工バイパスの場合
    if analysis.bypass_eligible and output_format == "mp3":
        cmd = [
            "ffmpeg", "-y", "-nostats", "-loglevel", "error",
            "-i", str(input_path),
            "-c:a", "copy",
            "-map_metadata", "-1",  # タグはtagger.pyで安全に移植
            str(output_path)
        ]
        subprocess.run(cmd, check=True)
        return

    # 2. フィルタグラフ構築
    gain = analysis.effective_gain_db
    if analysis.limiter_required:
        # 4x オーバーサンプリング相当 (192kHz) でリミッターをかけ、48kHzに戻す
        af_filter = (
            f"volume={gain:.2f}dB,"
            f"aresample=192000,"
            f"alimiter=limit={PEAK_CEILING_DBTP:.1f}dB:attack=5:release=50:asc=0:asc_level=1.0,"
            f"aresample=48000"
        )
    else:
        af_filter = f"volume={gain:.2f}dB"

    # 3. エンコーダ設定
    if output_format == "mp3":
        enc_opts = ["-c:a", "libmp3lame", "-b:a", "320k", "-id3v2_version", "3", "-write_id3v1", "1"]
    elif output_format == "aiff":
        enc_opts = ["-c:a", "pcm_s24be", "-ar", "48000"]
    else:
        raise ValueError(f"Unsupported output format: {output_format}")

    cmd = [
        "ffmpeg", "-y", "-nostats", "-loglevel", "error",
        "-i", str(input_path),
        "-vn", "-sn", "-dn",
        "-af", af_filter,
        *enc_opts,
        "-map_metadata", "-1",  # タグはmutagenで移植
        str(output_path)
    ]
    subprocess.run(cmd, check=True)
```

---

### 2.4 `volume_stabilizer/core/tagger.py`
Serato GEOB フレームを含む全メタデータの完全移植と、ReplayGainタグの削除。

```python
import mutagen
from mutagen.id3 import ID3, ID3NoHeaderError, GEOB, APIC, TBPM, TKEY
from mutagen.aiff import AIFF
from mutagen.mp3 import MP3
from pathlib import Path

SERATO_GEOB_DESCRIPTIONS = [
    "Serato Markers_",
    "Serato Markers2",
    "Serato Beatgrid",
    "Serato Autotags",
    "Serato Overview"
]

def copy_metadata(source_path: Path, target_path: Path, preserve_existing_target: bool = False) -> None:
    """
    source_path からメタデータを読み取り、target_path に移植する。
    preserve_existing_target が True（--force時）の場合、既存のtarget_pathのCue・タグを優先。
    """
    read_source = target_path if preserve_existing_target and target_path.exists() else source_path
    src_file = mutagen.File(str(read_source))
    if src_file is None:
        return

    dst_file = mutagen.File(str(target_path))
    if dst_file is None:
        return

    # ID3v2タグコンテナの初期化 (MP3 または AIFF)
    if dst_file.tags is None:
        dst_file.add_tags()

    # 1. ソースがID3を持つ場合 (MP3, AIFF, WAV)
    if hasattr(src_file, "tags") and src_file.tags is not None:
        for key, frame in src_file.tags.items():
            # ReplayGain / R128 タグは破棄
            if "REPLAYGAIN" in key.upper() or "R128" in key.upper():
                continue
            # Serato GEOBフレームは完全保持
            if isinstance(frame, GEOB):
                dst_file.tags.setall(frame.HashKey, [frame])
            else:
                try:
                    dst_file.tags[key] = frame
                except Exception:
                    pass

    # 2. ソースがFLAC / VorbisCommentの場合のSeratoタグ・標準タグ抽出
    elif hasattr(src_file, "items"):
        for k, v in src_file.items():
            k_upper = k.upper()
            if "REPLAYGAIN" in k_upper:
                continue
            if k_upper == "BPM":
                dst_file.tags["TBPM"] = TBPM(encoding=3, text=v)
            elif k_upper in ("KEY", "INITIALKEY"):
                dst_file.tags["TKEY"] = TKEY(encoding=3, text=v)

    # 保存
    dst_file.save()
```

---

### 2.5 `volume_stabilizer/core/backup.py`
強制再処理（--force）実行時に既存出力を退避。

```python
import shutil
from datetime import datetime
from pathlib import Path

def backup_existing_output(output_path: Path, backup_root: Path) -> Path:
    """
    既存の出力ファイルを /output/.backup/<YYYYMMDD_HHMMSS>/<rel_path> に安全退避。
    """
    if not output_path.exists():
        return None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest_path = backup_root / timestamp / output_path.name
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(output_path), str(dest_path))
    return dest_path
```

---

## 3. テスト計画と検証コマンド

### 単体テスト
```bash
# 仮想環境準備
uv sync

# コアテスト実行
pytest tests/ -v
```

### 検証項目
1. `test_hasher`: 同一音源のID3タグをmutagenで書き換えた後、`compute_audio_hash` の結果が完全に一致することを確認。
2. `test_analyzer`: 合成した -18 LUFS および -6 LUFS の音声に対して、正しいゲイン量とリミッター要否、3dBリダクション上限が算出されることを確認。
3. `test_processor`: 出力ファイルのEBU R128再解析結果が -10.0 LUFS ±0.3 LU 以内に収まることを確認。
4. `test_tagger`: Serato Markers2 (GEOB) を付与したテストファイルを作成し、変換後の MP3 / AIFF に完全同一バイナリで保持されていることをバイナリ比較で確認。
5. `test_bypass`: -10.1 LUFS / -1.2 dBTP の MP3 ファイルが無加工コピー（同一ハッシュ）されることを確認。
