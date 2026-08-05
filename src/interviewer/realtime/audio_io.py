from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from dataclasses import dataclass
from typing import Any

import numpy as np
import sounddevice as sd

from ..core.errors import AudioDeviceError

logger = logging.getLogger(__name__)

_INT16_MAX = 32768.0
_LEVEL_GAIN = 3.2  # 可视化放大系数，让正常说话时波形有明显起伏


def _rms_level(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float32)))))
    return min(1.0, rms / _INT16_MAX * _LEVEL_GAIN)


@dataclass(frozen=True, slots=True)
class AudioDeviceInfo:
    index: int
    name: str
    max_input: int
    max_output: int


def list_devices() -> list[AudioDeviceInfo]:
    try:
        raw: Any = sd.query_devices()
    except Exception as exc:
        raise AudioDeviceError(str(exc)) from exc
    return [
        AudioDeviceInfo(
            index=i,
            name=str(d.get("name", f"设备 {i}")),
            max_input=int(d.get("max_input_channels", 0)),
            max_output=int(d.get("max_output_channels", 0)),
        )
        for i, d in enumerate(raw)
    ]


def input_devices() -> list[AudioDeviceInfo]:
    return [d for d in list_devices() if d.max_input > 0]


def output_devices() -> list[AudioDeviceInfo]:
    return [d for d in list_devices() if d.max_output > 0]


def _resolve_device(name: str, *, want_input: bool) -> int | None:
    if not name:
        return None
    pool = input_devices() if want_input else output_devices()
    for device in pool:
        if device.name == name:
            return device.index
    for device in pool:
        if name in device.name:
            return device.index
    logger.warning("未找到音频设备「%s」，改用系统默认", name)
    return None


class AudioCapture:
    """麦克风采集。回调运行在 PortAudio 线程，只做搬运，不碰事件循环之外的状态。"""

    def __init__(
        self,
        *,
        sample_rate: int,
        loop: asyncio.AbstractEventLoop,
        device_name: str = "",
        block_ms: int = 40,
        gain: float = 1.0,
    ) -> None:
        self._sample_rate = sample_rate
        self._loop = loop
        self._device = _resolve_device(device_name, want_input=True)
        self._blocksize = max(160, int(sample_rate * block_ms / 1000))
        self._gain = gain
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=64)
        self._stream: sd.InputStream | None = None
        self._level = 0.0
        self._muted = False

    @property
    def level(self) -> float:
        return 0.0 if self._muted else self._level

    @property
    def muted(self) -> bool:
        return self._muted

    def set_muted(self, muted: bool) -> None:
        self._muted = muted

    def set_gain(self, gain: float) -> None:
        self._gain = max(0.2, min(4.0, gain))

    def start(self) -> None:
        if self._stream is not None:
            return

        def callback(indata: np.ndarray, _frames: int, _time: Any, status: sd.CallbackFlags) -> None:
            if status:
                logger.debug("采集状态: %s", status)
            mono = indata[:, 0] if indata.ndim == 2 else indata
            if self._gain != 1.0:
                mono = np.clip(mono.astype(np.float32) * self._gain, -32768, 32767).astype(np.int16)
            self._level = _rms_level(mono)
            if self._muted:
                return
            payload = mono.tobytes()
            self._loop.call_soon_threadsafe(self._offer, payload)

        try:
            self._stream = sd.InputStream(
                samplerate=self._sample_rate,
                channels=1,
                dtype="int16",
                blocksize=self._blocksize,
                device=self._device,
                callback=callback,
            )
            self._stream.start()
        except Exception as exc:
            self._stream = None
            raise AudioDeviceError(f"麦克风打开失败: {exc}") from exc
        logger.info("采集启动 %d Hz block=%d device=%s", self._sample_rate, self._blocksize, self._device)

    def _offer(self, payload: bytes) -> None:
        if self._queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
        self._queue.put_nowait(payload)

    async def read(self) -> bytes:
        return await self._queue.get()

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                logger.debug("关闭采集流异常", exc_info=True)
        self._level = 0.0
        while not self._queue.empty():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()


class AudioPlayer:
    """面试官语音播放。内部环形缓冲，打断时整体丢弃未播完的音频。"""

    def __init__(
        self,
        *,
        sample_rate: int,
        device_name: str = "",
        buffer_ms: int = 180,
        block_ms: int = 20,
    ) -> None:
        self._sample_rate = sample_rate
        self._device = _resolve_device(device_name, want_input=False)
        self._blocksize = max(120, int(sample_rate * block_ms / 1000))
        self._capacity = max(self._blocksize * 4, int(sample_rate * buffer_ms / 1000) * 4)
        self._buffer = np.zeros(self._capacity, dtype=np.int16)
        self._read = 0
        self._length = 0
        self._lock = threading.Lock()
        self._stream: sd.OutputStream | None = None
        self._level = 0.0
        self._epoch = 0
        # 已真正送到声卡的样本，供回声门控做参考信号
        self._ref_capacity = int(sample_rate * 0.6)
        self._ref = np.zeros(self._ref_capacity, dtype=np.int16)
        self._ref_pos = 0
        self._ref_filled = 0

    @property
    def level(self) -> float:
        return self._level

    @property
    def pending_ms(self) -> int:
        with self._lock:
            return int(self._length * 1000 / self._sample_rate)

    def start(self) -> None:
        if self._stream is not None:
            return

        def callback(outdata: np.ndarray, frames: int, _time: Any, status: sd.CallbackFlags) -> None:
            if status:
                logger.debug("播放状态: %s", status)
            chunk = self._pull(frames)
            outdata[:, 0] = chunk
            self._level = _rms_level(chunk)

        try:
            self._stream = sd.OutputStream(
                samplerate=self._sample_rate,
                channels=1,
                dtype="int16",
                blocksize=self._blocksize,
                device=self._device,
                callback=callback,
            )
            self._stream.start()
        except Exception as exc:
            self._stream = None
            raise AudioDeviceError(f"扬声器打开失败: {exc}") from exc
        logger.info("播放启动 %d Hz block=%d device=%s", self._sample_rate, self._blocksize, self._device)

    def push(self, pcm: bytes, epoch: int | None = None) -> None:
        """epoch 用于丢弃打断前残留的分片。"""
        if not pcm:
            return
        samples = np.frombuffer(pcm, dtype=np.int16)
        with self._lock:
            if epoch is not None and epoch != self._epoch:
                return
            available = self._capacity - self._length
            if samples.size > available:
                drop = samples.size - available
                self._read = (self._read + drop) % self._capacity
                self._length -= drop
            write = (self._read + self._length) % self._capacity
            first = min(samples.size, self._capacity - write)
            self._buffer[write : write + first] = samples[:first]
            rest = samples.size - first
            if rest > 0:
                self._buffer[:rest] = samples[first:]
            self._length += samples.size

    def _pull(self, frames: int) -> np.ndarray:
        out = np.zeros(frames, dtype=np.int16)
        with self._lock:
            take = min(frames, self._length)
            if take > 0:
                first = min(take, self._capacity - self._read)
                out[:first] = self._buffer[self._read : self._read + first]
                rest = take - first
                if rest > 0:
                    out[first:take] = self._buffer[:rest]
                self._read = (self._read + take) % self._capacity
                self._length -= take
            self._push_reference(out)
        return out

    def _push_reference(self, chunk: np.ndarray) -> None:
        size = chunk.size
        if size == 0 or size > self._ref_capacity:
            return
        end = self._ref_pos + size
        if end <= self._ref_capacity:
            self._ref[self._ref_pos : end] = chunk
        else:
            head = self._ref_capacity - self._ref_pos
            self._ref[self._ref_pos :] = chunk[:head]
            self._ref[: size - head] = chunk[head:]
        self._ref_pos = end % self._ref_capacity
        self._ref_filled = min(self._ref_capacity, self._ref_filled + size)

    def reference_tail(self, samples: int) -> np.ndarray:
        """按时间顺序返回最近送出的样本，供回声相关性判定。"""
        with self._lock:
            count = min(samples, self._ref_filled)
            if count <= 0:
                return np.zeros(0, dtype=np.int16)
            start = (self._ref_pos - count) % self._ref_capacity
            if start + count <= self._ref_capacity:
                return self._ref[start : start + count].copy()
            head = self._ref_capacity - start
            return np.concatenate((self._ref[start:], self._ref[: count - head]))

    def clear(self) -> int:
        """清空缓冲并推进 epoch，返回新 epoch。"""
        with self._lock:
            self._read = 0
            self._length = 0
            self._epoch += 1
            self._level = 0.0
            self._ref_filled = 0
            self._ref_pos = 0
            return self._epoch

    @property
    def epoch(self) -> int:
        with self._lock:
            return self._epoch

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                logger.debug("关闭播放流异常", exc_info=True)
        self.clear()
