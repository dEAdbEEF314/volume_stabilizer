import subprocess
from pathlib import Path
import pytest
from mutagen.id3 import ID3, TIT2, TPE1, TBPM, TKEY, GEOB, ID3NoHeaderError
from mutagen.mp3 import MP3


@pytest.fixture
def test_audio_generator(tmp_path: Path):
    def _generate(
        filename: str,
        duration: float = 3.0,
        frequency: int = 440,
        volume: float = 0.5,
    ) -> Path:
        out_path = tmp_path / filename
        cmd = [
            "ffmpeg",
            "-y",
            "-nostats",
            "-loglevel", "error",
            "-f", "lavfi",
            "-i", f"sine=frequency={frequency}:duration={duration}",
            "-af", f"volume={volume}",
            str(out_path),
        ]
        subprocess.run(cmd, check=True)
        return out_path

    return _generate
