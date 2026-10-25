# Volume Stabilizer 🎛️

**Volume Stabilizer** は、DJがクラブやフェスの現場で再生する音源ライブラリの体感音量（ラウドネス）を統一するための音響スタビライザー＆管理システムです。

EBU R128（Integrated LUFS）に基づく音響解析を行い、元音源を損なわない別ディレクトリ出力方式で均一化します。直感的なWeb UIと、スクリプト自動化に対応したCLI（`vstab`）の両方を提供します。

---

## ✨ 主な特徴

- **DJ現場に最適化されたラウドネス**:
  - 目標ラウドネス: **-10.0 LUFS**（rekordbox Auto Gain水準に準拠、ダイナミクスを重視）
  - トゥルーピーク上限: **-1.0 dBTP**（インターサンプルピークによる音割れを防止）
  - リミッター上限: **最大 3.0 dB**（過度なコンプレッションによるキックのアタック潰れ・歪みを防止）
- **非破壊・別出力方式**:
  - 元音源（`/music`）は読み取り専用（Read-Only）で保護
  - 入力側のフォルダ階層を完全再現して出力（`/output`）
- **DJメタデータ＆Serato Cueの完全保護**:
  - BPM、Key、アートワークに加え、**Serato DJのCueポイント/Beatgrid情報（GEOBフレーム）を完全保持**
  - 不整合の原因となる既存の ReplayGain / R128 タグは自動削除
- **音声ハッシュによる差分・再処理スキップ**:
  - メタデータを除外した純粋な音声ストリームの **SHA-256 ハッシュ**で判定
  - タグ編集やファイル名変更があっても二重処理を防止
  - `--force` による強制再処理時は、既存出力ファイルのCue情報を新出力へ引き継ぎ、旧出力を自動バックアップ（`/output/.backup`）
- **スマート・フォーマット出力**:
  - ロッシー音源（MP3, AAC/M4A） &rarr; **MP3 320kbps CBR**
  - ロスレス音源（WAV, AIFF, FLAC, ALAC） &rarr; **AIFF 24bit / 48kHz**
  - 目標ラウドネス内（±0.5 LU）のMP3は**無加工ストリームコピー**（再圧縮劣化ゼロ）
- **2段階ワークフロー Web UI ＆ CLI**:
  - Web UI: フォルダ選択 &rarr; 解析一覧プレビュー（除外チェック） &rarr; スタビライズ変換実行
  - 解析一覧は **To Do / Processed の2タブ**で表示（初期表示は To Do）。処理済み（Stabilized / Bypassed）は To Do タブ下部の折りたたみ見出し `Processed: N tracks` からも展開でき、開閉状態はブラウザに記憶されます
  - 「Select All」は表示中ページの行のみが対象で、選択状態はページを跨いで保持されます（「N selected」で選択数を確認可能）。「Stabilize Selected」はアクティブなタブの全ページの選択トラックを対象にします。処理済みを再処理する場合は Processed タブで対象を選び、`Force Reprocess` を有効にして実行
  - **表示件数**: Select All の横の `Rows` プルダウンで `10 / 20 / 50 / 100 / ALL` を選択（初期値 `10`、ブラウザに記憶）。To Do / Processed タブでは1ページの行数、To Do 下部の展開部では先頭N件の表示件数になります（残りは Processed タブへ誘導）
  - **ページ切り替え**: 一覧の下に `« First | ‹ Prev | 現在ページ中心の最大5ページ | Next › | Last »` と `11–20 / 57` の範囲表示を表示（1ページに収まる場合・`ALL` 選択時は非表示）
  - CLI: `vstab scan`, `vstab analyze`, `vstab convert --force`

---

## 🚀 クイックスタート (Docker Compose)

### 1. 設定ファイルの準備 (`.env`)

テンプレート `.env.example` をコピーして `.env` を作成します（パスやポート番号、目標音量などを変更できます）。

```bash
cp .env.example .env
```

主な設定項目（`.env` を直接テキストエディタで編集可能）:
- **`MUSIC_DIR`**: 元音源フォルダ（例: `/volume1/music` (NAS), `./music`）※安全のためコンテナからは読み取り専用
- **`OUTPUT_DIR`**: 統一音源の出力先フォルダ（例: `/volume1/dj_output`, `./output`）
- **`DATA_DIR`**: DB/キャッシュ保存先（デフォルト: `./data` ※高速なSSDを推奨）
- **`PORT`**: Web UI のポート番号（デフォルト: `8080`）
- **`VS_TARGET_LUFS`**: 目標ラウドネス（デフォルト: `-10.0` LUFS）
- **`VS_WORKERS`**: 並列ワーカー数（デフォルト: `0` = 自動: CPUコア数 - 1。NAS等でCPU負荷を抑えたい場合は `2` など）

### 2. 起動

```bash
docker compose up -d
```

起動後、ブラウザで `http://localhost:8080`（または `.env` で設定したポート）にアクセスしてください。

---

## 💻 CLI の使い方 (`vstab`)

Docker コンテナ内で直接、またはホストから `docker compose exec app vstab` で実行できます。

```bash
# 1. 音源フォルダのスキャン（検出ファイル一覧）
vstab scan [サブフォルダ]

# 2. Stage 1: ラウドネス解析（LUFS / True Peak / ゲイン一覧表示）
vstab analyze [サブフォルダ]

# 3. Stage 2: スタビライズ変換（差分スキップ付き）
vstab convert [サブフォルダ]

# 4. 強制再処理（既存の出力Cueを引き継ぎ、旧ファイルをバックアップ）
vstab convert [サブフォルダ] --force

# 5. 単一ファイルの検査
vstab inspect /music/House/track.flac

# 6. CSV レポートの出力
vstab export --output=report.csv
```

---

## 🎧 DJ運用における注意点

1. **Cue打ち・プレイリスト作成のタイミング**:
   - 本システムで処理した `/output` 配下の音源に対して、DJソフト（Serato, rekordbox 等）でCue打ちやグリッド調整を行ってください。
2. **Rekordbox と Serato の仕様差**:
   - **Serato DJ**: Cue情報は音源ファイル内のID3タグ（GEOB）に保存されるため、ファイル移動やバックアップ時も保持されます。
   - **rekordbox**: Cue情報はPC本体のローカルDBに保存されます。出力フォルダのパス（階層・ファイル名）は変更しないようにしてください。
3. **強制再処理（`--force`）の安全設計**:
   - すでにCueを打った出力ファイルを再処理する場合、本システムは既存出力ファイルからSerato Cueタグを抽出し、新しく生成したファイルに自動移植します。また、旧出力ファイルは `/output/.backup/<日時>/` に退避されます。

---

## 🧪 テスト実行

```bash
# ローカル開発環境でのテスト
uv sync
uv run pytest -v
```

Web UI のフロントエンドロジック（`static/js/track_view.js`）は、dev 依存の `py-mini-racer`（V8）を使って pytest 内で検証されます（Node.js は不要）。

---

## 📜 ライセンス

MIT License

---

## ⚖️ FFmpeg のライセンスについて

本ソフトウェアは、音声の解析およびエンコード処理のために [FFmpeg](https://ffmpeg.org/) を利用しています。

- **実行形態**:
  - 本ソフトウェアは FFmpeg のライブラリを直接リンク（静的/動的リンク）しておらず、別個の独立した外部コマンドラインツール（CLI）としてプロセス起動（fork & exec）およびパイプ通信を行っています。
  - したがって、フリーソフトウェア財団（FSF）のガイドラインに基づき、本ソフトウェア（Volume Stabilizer）のソースコードは独立した別個の著作物として取り扱われ、MIT ライセンスのもとで公開・利用が可能です。
- **Docker コンテナ内の FFmpeg バイナリ**:
  - 提供される Docker イメージに含まれる FFmpeg は、Debian 公式リポジトリのパッケージ（`apt-get install ffmpeg`）を利用しています。
  - このパッケージは `--enable-gpl` および `--enable-libmp3lame` を有効にしてビルドされているため、バイナリ全体として **GNU General Public License (GPL) v2+**（一部コンポーネントで v3+）が適用されます。
  - コンテナ内には FFmpeg の完全な著作権表示およびライセンス文（`/usr/share/doc/ffmpeg/copyright`）が保持されています。
- **ソースコードの入手先**:
  - FFmpeg のソースコードは、公式サイト（https://ffmpeg.org/download.html）または Debian のソースパッケージリポジトリ（`apt-get source ffmpeg`）よりいつでも入手可能です。
  - ビルド済みの Docker イメージをパブリックなレジストリ（Docker Hub 等）で再配布・公開する場合、上記 FFmpeg のライセンス案内およびソースコードの提供条項を遵守してください。
