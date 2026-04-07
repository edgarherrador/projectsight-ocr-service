"""
Quick-and-dirty OCR benchmark runner for Gemini models.

Usage example:
    uv run python scripts/benchmark_ocr.py --pdf-dir ./dataset

Optional price input format:
    --price gemini-3.1-pro-preview:1.25:5.00 --price gemini-2.5-pro:1.00:4.00
(values represent USD per 1M input tokens and USD per 1M output tokens)
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


MODEL_PROFILES = {
    "gemini-3.1-pro": {
        "context_window_tokens": 2_000_000,
        "max_output_tokens": 66_000,
        "pricing_per_1m": {
            "lte_200k": {"input": 2.00, "output": 12.00},
            "gt_200k": {"input": 4.00, "output": 18.00},
        },
    },
    "gemini-3.1-pro-preview": {
        "context_window_tokens": 2_000_000,
        "max_output_tokens": 66_000,
        "pricing_per_1m": {
            "lte_200k": {"input": 2.00, "output": 12.00},
            "gt_200k": {"input": 4.00, "output": 18.00},
        },
    },
    "gemini-2.5-pro": {
        "context_window_tokens": 2_000_000,
        "max_output_tokens": 8_000,
        "pricing_per_1m": {
            "lte_200k": {"input": 1.25, "output": 10.00},
            "gt_200k": {"input": 2.50, "output": 15.00},
        },
    },
}


def _resolve_model_profile(model_name: str) -> dict[str, Any] | None:
    normalized = _normalize_model_name(model_name)
    if normalized in MODEL_PROFILES:
        return MODEL_PROFILES[normalized]

    for key, profile in MODEL_PROFILES.items():
        if normalized.startswith(key):
            return profile

    return None


def _load_environment() -> None:
    """Load .env from repository root so script works from any cwd."""
    repo_root = Path(__file__).resolve().parents[1]
    dotenv_path = repo_root / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path=dotenv_path)


_load_environment()


def _normalize_model_name(model_name: str) -> str:
    cleaned = model_name.strip()
    if cleaned.startswith("models/"):
        cleaned = cleaned[len("models/") :]
    return cleaned


def _parse_prices(raw_prices: list[str]) -> dict[str, dict[str, float]]:
    prices: dict[str, dict[str, float]] = {}

    for entry in raw_prices:
        parts = [part.strip() for part in entry.split(":")]
        if len(parts) != 3:
            continue

        model_name = _normalize_model_name(parts[0])
        try:
            input_per_1m = float(parts[1])
            output_per_1m = float(parts[2])
        except ValueError:
            continue

        prices[model_name] = {
            "input_per_1m": input_per_1m,
            "output_per_1m": output_per_1m,
        }

    return prices


def _safe_percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None

    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]

    rank = (percentile / 100.0) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)

    if low == high:
        return ordered[low]

    fraction = rank - low
    return ordered[low] + (ordered[high] - ordered[low]) * fraction


def _estimate_cost(
    input_tokens: int | None,
    output_tokens: int | None,
    input_per_1m: float | None,
    output_per_1m: float | None,
) -> dict[str, float | None]:
    if (
        input_tokens is None
        or output_tokens is None
        or input_per_1m is None
        or output_per_1m is None
    ):
        return {
            "input_cost": None,
            "output_cost": None,
            "total_cost": None,
        }

    input_cost = (input_tokens / 1_000_000) * input_per_1m
    output_cost = (output_tokens / 1_000_000) * output_per_1m

    return {
        "input_cost": input_cost,
        "output_cost": output_cost,
        "total_cost": input_cost + output_cost,
    }


def _estimate_cost_tiered(
    model_name: str,
    input_tokens: int | None,
    output_tokens: int | None,
    manual_price_map: dict[str, dict[str, float]],
) -> dict[str, float | str | None]:
    if input_tokens is None or output_tokens is None:
        return {
            "price_tier": None,
            "input_per_1m": None,
            "output_per_1m": None,
            "input_cost": None,
            "output_cost": None,
            "total_cost": None,
            "price_source": None,
        }

    normalized = _normalize_model_name(model_name)
    manual = manual_price_map.get(normalized)
    if manual:
        cost = _estimate_cost(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_per_1m=manual.get("input_per_1m"),
            output_per_1m=manual.get("output_per_1m"),
        )
        return {
            "price_tier": "manual_override",
            "input_per_1m": manual.get("input_per_1m"),
            "output_per_1m": manual.get("output_per_1m"),
            "input_cost": cost["input_cost"],
            "output_cost": cost["output_cost"],
            "total_cost": cost["total_cost"],
            "price_source": "manual_override",
        }

    profile = _resolve_model_profile(normalized)
    if not profile:
        return {
            "price_tier": None,
            "input_per_1m": None,
            "output_per_1m": None,
            "input_cost": None,
            "output_cost": None,
            "total_cost": None,
            "price_source": None,
        }

    price_tier = "lte_200k" if input_tokens <= 200_000 else "gt_200k"
    tier_prices = profile["pricing_per_1m"][price_tier]
    cost = _estimate_cost(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_per_1m=tier_prices["input"],
        output_per_1m=tier_prices["output"],
    )
    return {
        "price_tier": price_tier,
        "input_per_1m": tier_prices["input"],
        "output_per_1m": tier_prices["output"],
        "input_cost": cost["input_cost"],
        "output_cost": cost["output_cost"],
        "total_cost": cost["total_cost"],
        "price_source": "built_in_2026",
    }


def _write_csv(records: list[dict[str, Any]], output_path: Path) -> None:
    fieldnames = [
        "file_name",
        "file_size_mb",
        "model",
        "success",
        "message",
        "total_pages",
        "non_empty_pages",
        "successful_pages",
        "failed_pages",
        "average_similarity",
        "latency_total_ms",
        "latency_p50_ms",
        "latency_p95_ms",
        "throughput_pages_per_min",
        "input_tokens_total",
        "output_tokens_total",
        "total_tokens_total",
        "effective_input_tokens_total",
        "effective_output_tokens_total",
        "effective_total_tokens_total",
        "token_count_method",
        "token_usage_available",
        "price_tier",
        "price_source",
        "price_input_per_1m",
        "price_output_per_1m",
        "estimated_input_cost_usd",
        "estimated_output_cost_usd",
        "estimated_total_cost_usd",
        "context_window_tokens",
        "max_output_tokens",
        "context_window_utilization_pct",
        "output_window_utilization_pct",
        "empty_output_rate",
        "internal_context_window_tokens",
        "timestamp_utc",
    ]

    with output_path.open("w", newline="", encoding="utf-8") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in records:
            writer.writerow(row)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run OCR benchmark over a PDF dataset")
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Gemini API key (overrides GEMINI_API_KEY env var)",
    )
    parser.add_argument("--pdf-dir", type=str, required=True, help="Directory containing PDF files")
    parser.add_argument("--glob", type=str, default="*.pdf", help="Glob pattern for PDF selection")
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        help="Model to benchmark (repeatable). If omitted, uses BENCHMARK_MODELS.",
    )
    parser.add_argument(
        "--price",
        action="append",
        default=[],
        help="Price entry format model:input_per_1m:output_per_1m (repeatable)",
    )
    parser.add_argument("--max-pages", type=int, default=None, help="Optional cap of pages per PDF")
    parser.add_argument(
        "--max-chars-per-page",
        type=int,
        default=12000,
        help="Cap extracted characters sent to model per page for faster benchmark runs",
    )
    parser.add_argument(
        "--ignore-size-limit",
        action="store_true",
        default=True,
        help="Ignore default file size limit using BENCHMARK_MAX_FILE_SIZE_MB",
    )
    parser.add_argument(
        "--output-json",
        type=str,
        default="benchmark_results.json",
        help="Output JSON file",
    )
    parser.add_argument(
        "--output-csv",
        type=str,
        default="benchmark_results.csv",
        help="Output CSV file",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.api_key:
        os.environ["GEMINI_API_KEY"] = args.api_key

    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not gemini_api_key:
        raise SystemExit(
            "Missing GEMINI_API_KEY. Set it in .env, export env var, "
            "or pass --api-key."
        )

    # Import after env is validated to avoid pydantic settings traceback.
    from api.gemini_service import process_pdf_with_gemini_with_metrics
    from config.settings import settings

    pdf_dir = Path(args.pdf_dir).resolve()
    if not pdf_dir.exists() or not pdf_dir.is_dir():
        raise SystemExit(f"PDF directory not found: {pdf_dir}")

    pdf_files = sorted(pdf_dir.glob(args.glob))
    if not pdf_files:
        raise SystemExit(f"No PDF files found in {pdf_dir} with pattern {args.glob}")

    requested_models = args.model if args.model else settings.get_benchmark_models()
    models = [_normalize_model_name(model) for model in requested_models]
    if not models:
        raise SystemExit("No benchmark models configured. Set --model or BENCHMARK_MODELS.")

    price_map = settings.get_benchmark_price_map()
    cli_prices = _parse_prices(args.price)
    price_map.update(cli_prices)

    all_results: list[dict[str, Any]] = []

    print(f"Running benchmark for {len(pdf_files)} PDFs and {len(models)} models")
    print(f"Models: {', '.join(models)}")

    for pdf_path in pdf_files:
        file_content = pdf_path.read_bytes()
        file_size_mb = len(file_content) / (1024 * 1024)

        print(f"\nPDF: {pdf_path.name} ({file_size_mb:.2f} MB)")

        for model_name in models:
            print(f"  -> Model: {model_name}")
            success, markdown_content, message, metrics = process_pdf_with_gemini_with_metrics(
                file_content=file_content,
                model_override=model_name,
                max_pages=args.max_pages,
                ignore_size_limit=args.ignore_size_limit,
                max_chars_per_page=args.max_chars_per_page,
            )

            page_metrics = metrics.get("page_metrics", [])
            latencies = [
                float(item.get("latency_ms", 0.0))
                for item in page_metrics
                if not item.get("skipped_empty")
            ]

            total_latency_ms = float(metrics.get("total_latency_ms", 0.0) or 0.0)
            non_empty_pages = int(metrics.get("non_empty_pages", 0) or 0)
            successful_pages = int(metrics.get("successful_pages", 0) or 0)
            failed_pages = int(metrics.get("failed_pages", 0) or 0)

            throughput_pages_per_min = None
            if total_latency_ms > 0:
                throughput_pages_per_min = (successful_pages / total_latency_ms) * 60_000

            input_tokens_total = metrics.get("input_tokens_total")
            output_tokens_total = metrics.get("output_tokens_total")
            total_tokens_total = metrics.get("total_tokens_total")
            effective_input_tokens_total = metrics.get("effective_input_tokens_total")
            effective_output_tokens_total = metrics.get("effective_output_tokens_total")
            effective_total_tokens_total = metrics.get("effective_total_tokens_total")

            cost = _estimate_cost_tiered(
                model_name=model_name,
                input_tokens=effective_input_tokens_total,
                output_tokens=effective_output_tokens_total,
                manual_price_map=price_map,
            )

            profile = _resolve_model_profile(model_name)
            context_window_tokens = profile.get("context_window_tokens") if profile else None
            max_output_tokens = profile.get("max_output_tokens") if profile else None

            context_window_utilization_pct = None
            if context_window_tokens and effective_input_tokens_total is not None:
                context_window_utilization_pct = (
                    effective_input_tokens_total / context_window_tokens
                ) * 100.0

            output_window_utilization_pct = None
            if max_output_tokens and effective_output_tokens_total is not None:
                output_window_utilization_pct = (
                    effective_output_tokens_total / max_output_tokens
                ) * 100.0

            empty_outputs = sum(
                1
                for item in page_metrics
                if not item.get("skipped_empty") and int(item.get("output_chars", 0)) == 0
            )
            empty_output_rate = (
                (empty_outputs / non_empty_pages) if non_empty_pages > 0 else None
            )

            row = {
                "file_name": pdf_path.name,
                "file_size_mb": round(file_size_mb, 4),
                "model": model_name,
                "success": success,
                "message": message,
                "total_pages": metrics.get("total_pages"),
                "non_empty_pages": non_empty_pages,
                "successful_pages": successful_pages,
                "failed_pages": failed_pages,
                "average_similarity": metrics.get("average_similarity"),
                "latency_total_ms": total_latency_ms,
                "latency_p50_ms": _safe_percentile(latencies, 50),
                "latency_p95_ms": _safe_percentile(latencies, 95),
                "throughput_pages_per_min": throughput_pages_per_min,
                "input_tokens_total": input_tokens_total,
                "output_tokens_total": output_tokens_total,
                "total_tokens_total": total_tokens_total,
                "effective_input_tokens_total": effective_input_tokens_total,
                "effective_output_tokens_total": effective_output_tokens_total,
                "effective_total_tokens_total": effective_total_tokens_total,
                "token_count_method": metrics.get("token_count_method"),
                "token_usage_available": metrics.get("token_usage_available", False),
                "price_tier": cost["price_tier"],
                "price_source": cost["price_source"],
                "price_input_per_1m": cost["input_per_1m"],
                "price_output_per_1m": cost["output_per_1m"],
                "estimated_input_cost_usd": cost["input_cost"],
                "estimated_output_cost_usd": cost["output_cost"],
                "estimated_total_cost_usd": cost["total_cost"],
                "context_window_tokens": context_window_tokens,
                "max_output_tokens": max_output_tokens,
                "context_window_utilization_pct": context_window_utilization_pct,
                "output_window_utilization_pct": output_window_utilization_pct,
                "empty_output_rate": empty_output_rate,
                "internal_context_window_tokens": metrics.get("internal_context_window_tokens"),
                "timestamp_utc": datetime.now(UTC).isoformat(),
                "used_models": metrics.get("used_models", []),
                "errors": metrics.get("errors", []),
                "page_metrics": page_metrics,
                "markdown_preview": markdown_content[:500],
            }
            all_results.append(row)

            similarity = row["average_similarity"]
            similarity_text = f"{similarity:.4f}" if isinstance(similarity, float) else "n/a"
            print(
                "     "
                f"success={success} pages={successful_pages}/{non_empty_pages} "
                f"sim={similarity_text} latency_ms={total_latency_ms:.0f} "
                f"cost_usd={cost['total_cost']} tier={cost['price_tier']}"
            )

    output_json = Path(args.output_json).resolve()
    output_csv = Path(args.output_csv).resolve()

    json_payload = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "pdf_dir": str(pdf_dir),
        "models": models,
        "prices": price_map,
        "results": all_results,
    }
    output_json.write_text(json.dumps(json_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    csv_rows = [
        {
            key: value
            for key, value in row.items()
            if key not in {"used_models", "errors", "page_metrics", "markdown_preview"}
        }
        for row in all_results
    ]
    _write_csv(csv_rows, output_csv)

    print("\nBenchmark complete")
    print(f"JSON: {output_json}")
    print(f"CSV:  {output_csv}")


if __name__ == "__main__":
    main()
