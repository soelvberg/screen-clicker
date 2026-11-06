from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import mss
from PIL import Image
from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter

from .matching import Box, Line, Word


class OcrUnavailable(RuntimeError):
    pass


@dataclass
class ScanResult:
    lines: list[Line]
    duration_ms: float
    origin: tuple[int, int]
    size: tuple[int, int]
    bgra: bytes

    def image(self) -> Image.Image:
        return Image.frombytes("RGB", self.size, self.bgra, "raw", "BGRX")


class Detector:
    """Captures a screen region and runs Windows OCR on it. Use from a single thread."""

    def __init__(self, language: str = "en", max_height: int = 1440) -> None:
        lang = Language(language)
        if not OcrEngine.is_language_supported(lang):
            raise OcrUnavailable(
                f"Windows OCR language '{language}' is not installed. Install it with (admin PowerShell): "
                f'Add-WindowsCapability -Online -Name "Language.OCR~~~{lang.language_tag}~0.0.1.0"'
            )
        engine = OcrEngine.try_create_from_language(lang)
        if engine is None:
            raise OcrUnavailable(f"Could not create OCR engine for '{language}'")
        self._engine = engine
        self._max_height = max_height
        self._max_dim = OcrEngine.max_image_dimension
        self._sct = mss.mss()
        self._loop = asyncio.new_event_loop()

    def close(self) -> None:
        self._sct.close()
        self._loop.close()

    def scan(self, region: dict[str, int] | None = None) -> ScanResult:
        """OCR a screen region (left/top/width/height); defaults to the primary monitor."""
        started = time.perf_counter()
        monitor = region or self._sct.monitors[1]
        shot = self._sct.grab(monitor)
        width, height = shot.size
        bgra = bytes(shot.bgra)

        scale = min(1.0, self._max_height / height, self._max_dim / max(width, height))
        if scale < 1.0:
            size = (max(1, round(width * scale)), max(1, round(height * scale)))
            img = Image.frombytes("RGB", (width, height), bgra, "raw", "BGRX").resize(
                size, Image.Resampling.BILINEAR
            )
            data, fmt = img.convert("RGBA").tobytes(), BitmapPixelFormat.RGBA8
        else:
            size, data, fmt = (width, height), bgra, BitmapPixelFormat.BGRA8

        result = self._loop.run_until_complete(self._recognize(data, fmt, size))
        left, top = monitor["left"], monitor["top"]
        lines = [
            Line(
                tuple(
                    Word(
                        w.text,
                        Box(
                            round(left + w.bounding_rect.x / scale),
                            round(top + w.bounding_rect.y / scale),
                            round(w.bounding_rect.width / scale),
                            round(w.bounding_rect.height / scale),
                        ),
                    )
                    for w in line.words
                )
            )
            for line in result.lines
        ]
        duration = (time.perf_counter() - started) * 1000
        return ScanResult(lines, duration, (left, top), (width, height), bgra)

    async def _recognize(self, data: bytes, fmt: BitmapPixelFormat, size: tuple[int, int]):
        writer = DataWriter()
        writer.write_bytes(data)
        bitmap = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), fmt, size[0], size[1])
        return await self._engine.recognize_async(bitmap)
