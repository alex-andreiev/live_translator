"""CLI entry point for meeting/session log analysis."""
import argparse

from live_translator.ai.log_analyzer import parse_dt, run_cli


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze Live Translator logs from one meeting/session and generate detailed summary."
    )
    parser.add_argument("--log-dir", help="Custom log directory. Default comes from settings.")
    parser.add_argument("--start", type=parse_dt, help="Start datetime: YYYY-MM-DD HH:MM[:SS]")
    parser.add_argument("--end", type=parse_dt, help="End datetime: YYYY-MM-DD HH:MM[:SS]")
    parser.add_argument("--session-start", type=parse_dt, help="Meeting start datetime.")
    parser.add_argument(
        "--window-minutes",
        type=int,
        default=180,
        help="Window size for --session-start (default: 180).",
    )
    parser.add_argument("--latest", type=int, help="Analyze N latest logs.")
    parser.add_argument(
        "--include-translated",
        action="store_true",
        help="Include 'Translated' records in analysis context.",
    )
    parser.add_argument("--provider", help="LLM provider (ollama/openai/anthropic).")
    parser.add_argument("--model", help="LLM model name.")
    parser.add_argument(
        "--language",
        default="Russian",
        help="Output report language (default: Russian).",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return run_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())

