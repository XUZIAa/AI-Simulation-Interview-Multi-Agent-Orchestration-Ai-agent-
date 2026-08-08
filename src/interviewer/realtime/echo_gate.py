from __future__ import annotations

import logging

import numpy as np

from .audio_io import AudioPlayer
from .recorder import resample_int16

logger = logging.getLogger(__name__)

_MAX_DELAY_MS = 320  # 扬声器到麦克风的往返延迟上界
_CORR_THRESHOLD = 0.34  # 归一化互相关峰值超过它即判为回声
_ENERGY_MARGIN = 1.9  # 真人插话的能量通常明显高于回声
_STREAK_FRAMES = 12  # 命中回声后维持这么多帧的「正在抑制」状态（约 0.5 秒）


class EchoGate:
    """外放场景下识别扬声器回流。

    真人插话与面试官正在播放的内容不相关，回声与之高度相关，
    据此判定是否把该帧送上行，避免面试官被自己的声音打断。
    """

    def __init__(
        self,
        player: AudioPlayer,
        *,
        capture_rate: int,
        player_rate: int,
        enabled: bool = False,
    ) -> None:
        self._player = player
        self._capture_rate = capture_rate
        self._player_rate = player_rate
        self._ref_samples = int(player_rate * _MAX_DELAY_MS / 1000)
        self._enabled = enabled
        self._suppressed_frames = 0
        self._streak = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    @property
    def suppressed_frames(self) -> int:
        return self._suppressed_frames

    @property
    def suppressing(self) -> bool:
        """最近是否正在抑制回声。

        服务端的「候选人开始说话」可能由回声触发，靠这个状态区分
        真人插话与扬声器回流，否则面试官会被自己的声音打断。
        """
        return self._streak > 0

    def is_echo(self, frame: bytes) -> bool:
        if not self._enabled or self._player.pending_ms <= 0:
            return False
        mic = np.frombuffer(frame, dtype=np.int16)
        if mic.size == 0:
            return False
        reference = self._player.reference_tail(self._ref_samples + mic.size * 2)
        if reference.size < mic.size:
            return False

        mic_ref_rate = resample_int16(mic, self._capture_rate, self._player_rate).astype(np.float32)
        ref = reference.astype(np.float32)
        mic_energy = float(np.sqrt(np.mean(np.square(mic_ref_rate))))
        ref_energy = float(np.sqrt(np.mean(np.square(ref))))
        if mic_energy < 1.0 or ref_energy < 1.0:
            return False
        if mic_energy > ref_energy * _ENERGY_MARGIN:
            return False

        peak = _normalized_peak(mic_ref_rate, ref)
        if peak >= _CORR_THRESHOLD:
            self._suppressed_frames += 1
            self._streak = _STREAK_FRAMES
            return True
        self._streak = max(0, self._streak - 1)
        return False

    def reset(self) -> None:
        self._suppressed_frames = 0
        self._streak = 0


def _normalized_peak(mic: np.ndarray, ref: np.ndarray) -> float:
    """FFT 互相关的归一化峰值。两路无关时接近 0，回声时接近 1。"""
    mic = mic - mic.mean()
    ref = ref - ref.mean()
    size = 1 << (mic.size + ref.size - 1).bit_length()
    spectrum = np.fft.rfft(ref, size) * np.conj(np.fft.rfft(mic, size))
    corr = np.fft.irfft(spectrum, size)
    denom = float(np.linalg.norm(mic) * np.linalg.norm(ref))
    if denom <= 0.0:
        return 0.0
    return float(np.max(np.abs(corr[: ref.size])) / denom)
