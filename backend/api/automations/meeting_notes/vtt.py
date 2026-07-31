"""
Turn a Teams WebVTT transcript into clean, speaker-attributed plain text.

Teams transcript .vtt cues carry the speaker name in a <v ...> voice tag:

    WEBVTT

    00:00:03.000 --> 00:00:06.480
    <v Jane Adviser>Thanks for joining today.</v>

We collapse the cues into "Speaker: line" text and merge consecutive lines from
the same speaker, which is both cheaper to send to the model and easier for it to
attribute correctly. Speaker attribution must be on at tenant level or the names
are absent (options paper, section 3.2) — we degrade to unattributed text rather
than fail if that happens.
"""
from __future__ import annotations

import re

_VOICE_TAG = re.compile(r"<v\s+([^>]+)>(.*?)</v>", re.IGNORECASE | re.DOTALL)
_ANY_TAG = re.compile(r"<[^>]+>")
_TIMESTAMP_LINE = re.compile(r"-->")


def _strip_tags(text: str) -> str:
    return re.sub(r"\s+", " ", _ANY_TAG.sub("", text)).strip()


def parse_vtt(vtt_text: str) -> str:
    """Return speaker-attributed transcript text, one merged turn per line."""
    lines: list[tuple[str, str]] = []  # (speaker, text)
    for raw_block in re.split(r"\n\s*\n", vtt_text.replace("\r\n", "\n")):
        block = raw_block.strip()
        if not block or block.upper().startswith("WEBVTT"):
            continue
        # Drop cue-id and timestamp lines; keep the spoken content lines.
        content_lines = [
            ln for ln in block.split("\n")
            if ln.strip() and not _TIMESTAMP_LINE.search(ln)
        ]
        if not content_lines:
            continue
        joined = " ".join(content_lines)
        match = _VOICE_TAG.search(joined)
        if match:
            speaker = match.group(1).strip()
            spoken = _strip_tags(match.group(2))
        else:
            speaker = ""
            spoken = _strip_tags(joined)
        if not spoken:
            continue
        # Merge consecutive turns from the same speaker into one line.
        if lines and lines[-1][0] == speaker:
            lines[-1] = (speaker, f"{lines[-1][1]} {spoken}")
        else:
            lines.append((speaker, spoken))

    rendered = []
    for speaker, spoken in lines:
        rendered.append(f"{speaker}: {spoken}" if speaker else spoken)
    return "\n".join(rendered)
