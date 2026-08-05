from __future__ import annotations

import logging
import wave
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

import numpy as np

from ..core.paths import audio_dir

logger = logging.getLogger(__name__)

MASTER_RATE = 24000
_CHUNK_SAMPLES = 24000 * 4


def resample_int16(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate or samples.size == 0:
        return samples
    count = int(round(samples.size * dst_rate / src_rate))
    if count <= 0:
        return np.zeros(0, dtype=np.int16)
    source_x = np.arange(samples.size, dtype=np.float32)
    target_x = np.linspace(0.0, float(samples.size - 1), count, dtype=np.float32)
    return np.interp(target_x, source_x, samples.astype(np.float32)).astype(np.int16)


class _Track:
    """按时间轴顺序写入的单声道原始轨。空隙用静音补齐，保证两轨可对齐。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._file: BinaryIO = path.open("wb")
        self._samples_written = 0

    @property
    def path(self) -> Path:
        return self._path

    @property
    def samples(self) -> int:
        return self._samples_written

    def write_at(self, elapsed_ms: int, samples: np.ndarray) -> None:
        if samples.size == 0:
            return
        target = int(elapsed_ms * MASTER_RATE / 1000)
        gap = target - self._samples_written
        if gap > 0:
            self._file.write(np.zeros(gap, dtype=np.int16).tobytes())
            self._samples_written += gap
        self._file.write(samples.tobytes())
        self._samples_written += samples.size

    def pad_to(self, total_samples: int) -> None:
        gap = total_samples - self._samples_written
        if gap > 0:
            self._file.write(np.zeros(gap, dtype=np.int16).tobytes())
            self._samples_written += gap

    def close(self) -> None:
        if not self._file.closed:
            self._file.flush()
            self._file.close()

    def unlink(self) -> None:
        self.close()
        self._path.unlink(missing_ok=True)


class SessionRecorder:
    """双轨录制：左声道候选人，右声道面试官。合并后可直接回放整场对话。"""

    def __init__(self, session_id: int, *, candidate_rate: int, interviewer_rate: int) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self._stem = audio_dir() / f"session-{session_id}-{stamp}"
        self._candidate_rate = candidate_rate
        self._interviewer_rate = interviewer_rate
        self._candidate = _Track(self._stem.with_suffix(".cand.raw"))
        self._interviewer = _Track(self._stem.with_suffix(".intv.raw"))
        self._closed = False

    def write_candidate(self, elapsed_ms: int, pcm: bytes) -> None:
        if self._closed or not pcm:
            return
        samples = np.frombuffer(pcm, dtype=np.int16)
        self._candidate.write_at(elapsed_ms, resample_int16(samples, self._candidate_rate, MASTER_RATE))

    def write_interviewer(self, elapsed_ms: int, pcm: bytes) -> None:
        if self._closed or not pcm:
            return
        samples = np.frombuffer(pcm, dtype=np.int16)
        self._interviewer.write_at(
            elapsed_ms, resample_int16(samples, self._interviewer_rate, MASTER_RATE)
        )

    def finalize(self) -> Path | None:
        if self._closed:
            return None
        self._closed = True
        total = max(self._candidate.samples, self._interviewer.samples)
        self._candidate.pad_to(total)
        self._interviewer.pad_to(total)
        self._candidate.close()
        self._interviewer.close()
        if total == 0:
            self._candidate.unlink()
            self._interviewer.unlink()
            return None

        target = self._stem.with_suffix(".wav")
        try:
            with (
                self._candidate.path.open("rb") as left,
                self._interviewer.path.open("rb") as right,
                wave.open(str(target), "wb") as out,
            ):
                out.setnchannels(2)
                out.setsampwidth(2)
                out.setframerate(MASTER_RATE)
                while True:
                    lchunk = left.read(_CHUNK_SAMPLES * 2)
                    rchunk = right.read(_CHUNK_SAMPLES * 2)
                    if not lchunk and not rchunk:
                        break
                    lsamples = np.frombuffer(lchunk, dtype=np.int16)
                    rsamples = np.frombuffer(rchunk, dtype=np.int16)
                    size = max(lsamples.size, rsamples.size)
                    stereo = np.zeros((size, 2), dtype=np.int16)
                    stereo[: lsamples.size, 0] = lsamples
                    stereo[: rsamples.size, 1] = rsamples
                    out.writeframes(stereo.tobytes())
        except OSError:
            logger.exception("合并录音失败")
            return None
        finally:
            self._candidate.path.unlink(missing_ok=True)
            self._interviewer.path.unlink(missing_ok=True)
        logger.info("录音已保存: %s", target)
        return target

    def discard(self) -> None:
        self._closed = True
        self._candidate.unlink()
        self._interviewer.unlink()
