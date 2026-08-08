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

# 自动增益。基于原始样本前馈计算，不能用 _rms_level 那种被 clip 的可视化值，
# 否则削波之后拿不到"超了多少"的信息，只能反馈震荡。
_AGC_TARGET_RMS = 4200.0  # 说话时期望的 int16 均方根，服务端 VAD 在这一档最稳
_AGC_SILENCE_RMS = 220.0  # 低于此视为静音，不参与调整，避免放大底噪
_AGC_PEAK_LIMIT = 29000.0  # 放大后允许的峰值上界，硬性防削波
_AGC_MIN = 0.55  # 允许适度衰减：输入本身过响时靠它防削波
_AGC_MAX = 8.0
_AGC_SMOOTH = 0.12  # 每帧只朝目标移动这个比例，避免音量突变


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
        auto_gain: bool = True,
        initial_agc: float = 1.0,
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
        # 自动增益：不同麦克风的输入振幅差几倍，振幅不足会被服务端 VAD 当成静音
        self._auto_gain = auto_gain
        self._agc = min(_AGC_MAX, max(_AGC_MIN, initial_agc))
        self._silent_frames = 0

    @property
    def auto_gain_factor(self) -> float:
        return self._agc

    def take_silent_frames(self) -> int:
        """取走并清零静音帧计数，供链路统计判断上行里有多少是没说话的。"""
        count, self._silent_frames = self._silent_frames, 0
        return count

    def _tune_agc(self, raw: np.ndarray, rms: float) -> None:
        """按原始样本前馈算增益：目标 RMS / 当前 RMS，再夹在防削波上界内。

        必须用未放大的信号，否则放大后的读数会形成反馈环、在削波点来回震荡。
        """
        peak = float(np.max(np.abs(raw)))
        if peak > 0.0 and peak * self._agc >= _AGC_PEAK_LIMIT:
            # 已经要削波了，一步降到安全值，不走平滑
            self._agc = max(_AGC_MIN, _AGC_PEAK_LIMIT / peak)
            return
        wanted = _AGC_TARGET_RMS / rms
        if peak > 0.0:
            wanted = min(wanted, _AGC_PEAK_LIMIT / peak)
        wanted = min(_AGC_MAX, max(_AGC_MIN, wanted))
        self._agc += (wanted - self._agc) * _AGC_SMOOTH

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
            raw = mono.astype(np.float32)
            rms = float(np.sqrt(np.mean(np.square(raw))))
            voiced = rms >= _AGC_SILENCE_RMS
            # 先用原始信号定增益，再放大：顺序反过来会形成反馈环
            if self._auto_gain and voiced:
                self._tune_agc(raw, rms)
            # 静音期一律按原样上行。增益是为说话声定的，静音时沿用会把底噪
            # 一起抬高数倍，服务端 VAD 会当成候选人开口，进而掐掉面试官正在
            # 生成的响应——面试官因此一句话都说不出来。
            if not voiced:
                self._silent_frames += 1
            factor = self._gain * (self._agc if (self._auto_gain and voiced) else 1.0)
            if factor != 1.0:
                mono = np.clip(raw * factor, -32768, 32767).astype(np.int16)
            self._level = _rms_level(mono)
            if self._muted:
                return
            self._loop.call_soon_threadsafe(self._offer, mono.tobytes())

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
    """面试官语音播放。

    带抖动缓冲：实时语音的音频块是突发到达的，一有空档就用静音补会造成
    每个回调都断一下，听感上像卡顿且语速失真。改为先蓄水到水位再起播，
    中途被抽干就整体重新蓄水，让声音要么连续、要么明确停顿。
    """

    def __init__(
        self,
        *,
        sample_rate: int,
        device_name: str = "",
        prefill_ms: int = 260,
        refill_ms: int = 140,
        capacity_ms: int = 4000,
        block_ms: int = 40,
    ) -> None:
        self._sample_rate = sample_rate
        self._device = _resolve_device(device_name, want_input=False)
        self._blocksize = max(160, int(sample_rate * block_ms / 1000))
        self._capacity = max(self._blocksize * 8, int(sample_rate * capacity_ms / 1000))
        self._prefill = int(sample_rate * max(prefill_ms, refill_ms) / 1000)
        self._refill = int(sample_rate * refill_ms / 1000)
        self._buffer = np.zeros(self._capacity, dtype=np.int16)
        self._read = 0
        self._length = 0
        self._priming = True
        self._draining = False
        self._started = False
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
            self._draining = False
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
            if self._priming and not self._draining:
                # 蓄水未达水位，先安静等着，别输出碎片。
                # 首句起播要稳，断流后重起用更低水位，恢复更快。
                threshold = self._refill if self._started else self._prefill
                if self._length < threshold:
                    self._push_reference(out)
                    return out
                self._priming = False
                self._started = True
            take = min(frames, self._length)
            if take > 0:
                first = min(take, self._capacity - self._read)
                out[:first] = self._buffer[self._read : self._read + first]
                rest = take - first
                if rest > 0:
                    out[first:take] = self._buffer[:rest]
                self._read = (self._read + take) % self._capacity
                self._length -= take
            if take < frames and not self._draining:
                # 被抽干了，整体重新蓄水，避免逐块断续
                self._priming = True
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

    def drain(self) -> None:
        """上游已说完：把残留播完，不再等水位，否则尾音会卡在缓冲里。"""
        with self._lock:
            self._draining = True
            self._priming = False

    def clear(self) -> int:
        """清空缓冲并推进 epoch，返回新 epoch。"""
        with self._lock:
            self._read = 0
            self._length = 0
            self._epoch += 1
            self._level = 0.0
            self._priming = True
            self._draining = False
            self._started = False
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
