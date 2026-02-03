"""
Meeting/session log analyzer for Live Translator.
"""
from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from live_translator.ai.api_client import APIClient
from live_translator.utils.settings import get_settings

LOG_FILENAME_RE = re.compile(r"^session_(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})\.log$")
LOG_ENTRY_RE = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\] (Original|Translated):\s*$")
MAX_CONTEXT_CHARS = 60000


@dataclass
class LogEntry:
    timestamp: datetime
    kind: str
    text: str


@dataclass
class ParsedLog:
    path: Path
    session_start: datetime
    entries: list[LogEntry]


class MeetingLogAnalyzer:
    """Aggregate nearby session logs and generate a meeting analysis."""

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        output_language: str = "Russian",
    ):
        settings = get_settings()
        self.output_language = output_language

        if provider is None:
            provider = settings.get("ai_assistant", "provider", "ollama")
        if model is None:
            if settings.get("ai_assistant", "use_translation_model", True):
                model = settings.get("translation", "model", "mistral:7b")
            else:
                model = settings.get("ai_assistant", "model", "mistral:7b")

        self._client = APIClient(provider=provider, model=model, timeout=90)

    @staticmethod
    def default_log_dir() -> Path:
        settings = get_settings()
        raw = settings.get("logging", "log_path", "~/.local/share/live-translator/logs")
        return Path(os.path.expanduser(raw))

    @staticmethod
    def _parse_filename_timestamp(path: Path) -> datetime | None:
        match = LOG_FILENAME_RE.match(path.name)
        if not match:
            return None
        date_part, time_part = match.groups()
        return datetime.strptime(f"{date_part}_{time_part}", "%Y-%m-%d_%H-%M-%S")

    def find_logs(
        self,
        log_dir: Path | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        latest: int | None = None,
    ) -> list[Path]:
        directory = log_dir or self.default_log_dir()
        if not directory.exists():
            return []

        files: list[tuple[datetime, Path]] = []
        for path in directory.glob("session_*.log"):
            ts = self._parse_filename_timestamp(path)
            if ts is None:
                continue
            if start and ts < start:
                continue
            if end and ts > end:
                continue
            files.append((ts, path))

        files.sort(key=lambda item: item[0])

        if latest is not None and latest > 0:
            return [path for _, path in files[-latest:]]
        return [path for _, path in files]

    def parse_log(self, path: Path) -> ParsedLog:
        session_start = self._parse_filename_timestamp(path)
        if session_start is None:
            session_start = datetime.fromtimestamp(path.stat().st_mtime)

        entries: list[LogEntry] = []
        current_time: datetime | None = None
        current_kind: str | None = None
        current_lines: list[str] = []

        def flush_current():
            if current_time and current_kind:
                text = "\n".join(line for line in current_lines if line.strip()).strip()
                if text:
                    entries.append(LogEntry(timestamp=current_time, kind=current_kind, text=text))

        with open(path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.rstrip("\n")
                match = LOG_ENTRY_RE.match(line)

                if match:
                    flush_current()
                    hhmmss, kind = match.groups()
                    clock = datetime.strptime(hhmmss, "%H:%M:%S").time()
                    current_time = datetime.combine(session_start.date(), clock)
                    current_kind = kind.lower()
                    current_lines = []
                    continue

                if current_time is None:
                    continue

                if line.startswith("=" * 10) or line.startswith("-" * 10):
                    flush_current()
                    current_time = None
                    current_kind = None
                    current_lines = []
                    continue

                current_lines.append(line)

        flush_current()
        return ParsedLog(path=path, session_start=session_start, entries=entries)

    def analyze_logs(self, logs: Iterable[Path], include_translated: bool = False) -> str:
        parsed_logs = [self.parse_log(path) for path in logs]
        timeline_lines: list[str] = []

        for parsed in parsed_logs:
            for entry in parsed.entries:
                if entry.kind == "translated" and not include_translated:
                    continue
                text = entry.text.replace("\n", " ").strip()
                if not text:
                    continue
                ts = entry.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                timeline_lines.append(f"[{ts}] {entry.kind.upper()}: {text}")

        if not timeline_lines:
            return (
                "Нет данных для анализа.\n"
                "- В логах не найдено записей типа Original.\n"
                "- Попробуйте добавить флаг --include-translated."
            )

        timeline_text = "\n".join(timeline_lines)
        if len(timeline_text) > MAX_CONTEXT_CHARS:
            timeline_text = timeline_text[-MAX_CONTEXT_CHARS:]

        first_ts = parsed_logs[0].session_start.strftime("%Y-%m-%d %H:%M:%S") if parsed_logs else "unknown"
        last_ts = parsed_logs[-1].session_start.strftime("%Y-%m-%d %H:%M:%S") if parsed_logs else "unknown"

        prompt = f"""You are a meeting analyst.
Create a detailed report in {self.output_language} based strictly on the transcript.
Do not invent facts.

Report structure:
1) Краткое summary встречи (4-8 предложений)
2) Что было сделано (конкретные действия/решения)
3) Важные вопросы (вопрос + контекст + статус, если виден)
4) Важные замечания клиента (только действительно важные)
5) Открытые вопросы и следующие шаги

If some section has insufficient data, explicitly write "Недостаточно данных".

Meta:
- Log files count: {len(parsed_logs)}
- Transcript lines: {len(timeline_lines)}
- Approximate window: {first_ts} .. {last_ts}

Transcript:
{timeline_text}
"""
        answer = self._client.generate(prompt)
        if answer and answer.strip():
            return answer.strip()
        return self._fallback_analysis(timeline_lines)

    @staticmethod
    def _fallback_analysis(timeline_lines: list[str]) -> str:
        questions = [line for line in timeline_lines if "?" in line][:12]
        client_notes = [
            line for line in timeline_lines
            if re.search(r"\b(client|клиент|важно|important|must|deadline|срок)\b", line, re.IGNORECASE)
        ][:12]

        actions = timeline_lines[:12]

        def to_bullets(lines: list[str]) -> str:
            return "\n".join(f"- {line}" for line in lines) if lines else "- Недостаточно данных"

        return (
            "Краткое summary встречи:\n"
            "Модель недоступна, поэтому ниже эвристический разбор по найденным репликам.\n\n"
            "Что было сделано:\n"
            f"{to_bullets(actions)}\n\n"
            "Важные вопросы:\n"
            f"{to_bullets(questions)}\n\n"
            "Важные замечания клиента:\n"
            f"{to_bullets(client_notes)}\n\n"
            "Открытые вопросы и следующие шаги:\n"
            "- Проверить подключение модели и запустить анализ повторно."
        )


def parse_dt(value: str) -> datetime:
    patterns = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
    ]
    for pattern in patterns:
        try:
            return datetime.strptime(value, pattern)
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        "Invalid datetime format. Use 'YYYY-MM-DD HH:MM[:SS]' or ISO 'YYYY-MM-DDTHH:MM[:SS]'."
    )


def build_time_window(args) -> tuple[datetime | None, datetime | None]:
    if args.session_start:
        start = args.session_start
        end = start + timedelta(minutes=args.window_minutes)
        return start, end
    return args.start, args.end


def run_cli(args: argparse.Namespace) -> int:
    analyzer = MeetingLogAnalyzer(
        provider=args.provider,
        model=args.model,
        output_language=args.language,
    )

    start, end = build_time_window(args)
    if start and end and end < start:
        print("Invalid range: --end must be greater than --start.")
        return 2

    logs = analyzer.find_logs(
        log_dir=Path(os.path.expanduser(args.log_dir)) if args.log_dir else None,
        start=start,
        end=end,
        latest=args.latest,
    )

    if not logs:
        print("No matching log files were found.")
        return 1

    print("Using logs:")
    for log in logs:
        print(f"- {log}")
    print("\nGenerating analysis...\n")

    report = analyzer.analyze_logs(logs, include_translated=args.include_translated)
    print(report)
    return 0
