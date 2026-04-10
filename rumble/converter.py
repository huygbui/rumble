DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHANNELS = 1
DEFAULT_FRAME_DURATION_MS = 20
DEFAULT_OUTPUT_SAMPLE_RATE = 24000
DEFAULT_OUTPUT_FRAME_DURATION_MS = 20


def _load_opuslib():
    try:
        import opuslib
    except Exception as exc:
        raise RuntimeError(
            "libopus is not available. On Windows, install libopus and add opus.dll to PATH before using Opus codecs."
        ) from exc

    return opuslib

class OpusPacketDecoder:
    def __init__(
        self,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        channels: int = DEFAULT_CHANNELS,
        frame_duration_ms: int = DEFAULT_FRAME_DURATION_MS,
    ) -> None:
        opuslib = _load_opuslib()
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_duration_ms = frame_duration_ms
        self.frame_size = (sample_rate * frame_duration_ms) // 1000
        self._opuslib = opuslib
        self._decoder = opuslib.Decoder(sample_rate, channels)

    def decode_packet(self, frame: bytes) -> bytes:
        if not frame:
            return b""
        try:
            return self._decoder.decode(frame, self.frame_size)
        except self._opuslib.OpusError as e:
            raise RuntimeError(f"opus decode failed: {e}") from e


class OpusPacketEncoder:
    def __init__(
        self,
        sample_rate: int = DEFAULT_OUTPUT_SAMPLE_RATE,
        channels: int = DEFAULT_CHANNELS,
        frame_duration_ms: int = DEFAULT_OUTPUT_FRAME_DURATION_MS,
    ) -> None:
        opuslib = _load_opuslib()
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_duration_ms = frame_duration_ms
        self.frame_size = (sample_rate * frame_duration_ms) // 1000
        self.bytes_per_sample = 2
        self.bytes_per_frame = self.frame_size * channels * self.bytes_per_sample
        self._opuslib = opuslib
        self._encoder = opuslib.Encoder(sample_rate, channels, opuslib.APPLICATION_AUDIO)
        self._buffer = bytearray()

    def encode_chunk(self, pcm_data: bytes) -> list[bytes]:
        if not pcm_data:
            return []
        self._buffer.extend(pcm_data)

        packets: list[bytes] = []
        while len(self._buffer) >= self.bytes_per_frame:
            frame = bytes(self._buffer[:self.bytes_per_frame])
            del self._buffer[:self.bytes_per_frame]
            packets.append(self._encode_frame(frame))

        return packets

    def flush(self) -> list[bytes]:
        if not self._buffer:
            return []
        padded_frame = bytes(self._buffer).ljust(self.bytes_per_frame, b"\x00")
        self._buffer.clear()
        return [self._encode_frame(padded_frame)]

    def _encode_frame(self, pcm_frame: bytes) -> bytes:
        try:
            return self._encoder.encode(pcm_frame, self.frame_size)
        except self._opuslib.OpusError as e:
            raise RuntimeError(f"opus encode failed: {e}") from e
