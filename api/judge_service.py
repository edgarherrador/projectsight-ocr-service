"""OCR quality judge with Gemini LLM evaluation and rule-based fallback."""
import json
import logging
import random
import time
from google import genai
from config.settings import settings


logger = logging.getLogger(__name__)

# Dedicated client for judge requests.
judge_client = genai.Client(api_key=settings.gemini_api_key)


def should_run_judge(is_cached: bool, similarity: float | None) -> tuple[bool, str]:
    """Decide whether the judge should run and return trigger reason."""
    if not settings.judge_enabled:
        return False, "disabled"

    if similarity is not None and similarity < settings.judge_similarity_threshold:
        return True, "low_similarity"

    if settings.judge_only_new_documents:
        if is_cached:
            return False, "cache_hit"
        return True, "new_document"

    if settings.judge_sample_rate > 0:
        if random.random() <= settings.judge_sample_rate:
            return True, "sampled"
        return False, "sampled_skip"

    return False, "policy_skip"


def _level_similarity(similarity: float | None) -> tuple[str, str]:
    if similarity is None:
        return "AMBER", "Similarity unavailable"
    if similarity >= 0.98:
        return "GREEN", "Similarity >= 0.98"
    if similarity >= 0.90:
        return "AMBER", "0.90 <= Similarity < 0.98"
    return "RED", "Similarity < 0.90"


def _level_cer(cer: float | None) -> tuple[str, str]:
    if cer is None:
        return "AMBER", "CER unavailable"
    if cer < 0.001:
        return "GREEN", "CER < 0.001"
    if cer <= 0.005:
        return "AMBER", "0.001 <= CER <= 0.005"
    return "RED", "CER > 0.005"


def _coerce_float(value: object) -> float | None:
    """Return float(value) when possible, otherwise None."""
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_levels(similarity: float | None, cer_estimate: float | None) -> list[dict]:
    """Build per-indicator severities for UI and persistence."""
    similarity_level, similarity_note = _level_similarity(similarity)
    cer_level, cer_note = _level_cer(cer_estimate)
    structural_level, structural_note = _level_similarity(similarity)

    return [
        {
            "score_name": "similarity",
            "value": similarity,
            "level": similarity_level,
            "threshold_note": similarity_note,
        },
        {
            "score_name": "cer_estimate",
            "value": cer_estimate,
            "level": cer_level,
            "threshold_note": cer_note,
        },
        {
            "score_name": "structural_fidelity_proxy",
            "value": similarity,
            "level": structural_level,
            "threshold_note": structural_note,
        },
    ]


def _evaluate_metrics_rules(metrics: dict, run_trigger: str) -> dict:
    """Existing deterministic rules kept as fallback and safety net."""
    similarity = _coerce_float(metrics.get("average_similarity"))

    cer_estimate = None if similarity is None else max(0.0, 1.0 - similarity)
    wer_estimate = None if similarity is None else max(0.0, 1.0 - (similarity * 0.98))
    levels = _build_levels(similarity, cer_estimate)

    if any(level["level"] == "RED" for level in levels):
        verdict = "REVIEW_MANUAL"
        semaphore = "RED"
        reason = "At least one quality metric is RED"
    elif any(level["level"] == "AMBER" for level in levels):
        verdict = "REVIEW_MANUAL"
        semaphore = "AMBER"
        reason = "At least one quality metric is AMBER"
    else:
        verdict = "APPROVED_AUTOMATICALLY"
        semaphore = "GREEN"
        reason = "All quality metrics are GREEN"

    return {
        "verdict": verdict,
        "semaphore": semaphore,
        "reason": reason,
        "run_trigger": run_trigger,
        "judge_model": settings.judge_model,
        "judge_mode": "rules",
        "cer_estimate": cer_estimate,
        "wer_estimate": wer_estimate,
        "levels": levels,
    }


def _build_llm_payload(
    metrics: dict,
    levels: list[dict],
    run_trigger: str,
    max_pages: int = 12,
) -> dict:
    """Prepare compact structured payload for Gemini to avoid oversized prompts."""
    page_metrics = metrics.get("page_metrics")
    page_candidates: list[dict] = []
    if isinstance(page_metrics, list):
        for item in page_metrics:
            if not isinstance(item, dict):
                continue
            if item.get("skipped_empty"):
                continue
            page_num = item.get("page_num")
            if not isinstance(page_num, int):
                continue
            similarity = _coerce_float(item.get("similarity"))
            page_candidates.append(
                {
                    "page_num": page_num,
                    "similarity": similarity,
                    "error": item.get("error") or "",
                    "source_excerpt": item.get("source_excerpt") or "",
                    "output_excerpt": item.get("output_excerpt") or "",
                }
            )

    page_candidates.sort(
        key=lambda p: (
            0 if _coerce_float(p.get("similarity")) is not None else 1,
            _coerce_float(p.get("similarity")) if _coerce_float(p.get("similarity")) is not None else 1.0,
        )
    )

    return {
        "run_trigger": run_trigger,
        "summary": {
            "average_similarity": _coerce_float(metrics.get("average_similarity")),
            "cer_estimate": _coerce_float(metrics.get("cer_estimate")),
            "wer_estimate": _coerce_float(metrics.get("wer_estimate")),
            "total_pages": metrics.get("total_pages"),
            "successful_pages": metrics.get("successful_pages"),
            "failed_pages": metrics.get("failed_pages"),
            "total_latency_ms": _coerce_float(metrics.get("total_latency_ms")),
            "effective_input_tokens_total": metrics.get("effective_input_tokens_total"),
            "effective_output_tokens_total": metrics.get("effective_output_tokens_total"),
            "estimated_total_cost_usd": _coerce_float(metrics.get("estimated_total_cost_usd")),
        },
        "levels": levels,
        "worst_pages": page_candidates[:max_pages],
        "errors": metrics.get("errors")[:10] if isinstance(metrics.get("errors"), list) else [],
    }


def _extract_json_object(text: str) -> dict | None:
    """Extract a JSON object from response text (plain or fenced)."""
    raw = (text or "").strip()
    if not raw:
        return None

    candidates = [raw]
    if "```" in raw:
        for chunk in raw.split("```"):
            cleaned = chunk.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            if cleaned.startswith("{") and cleaned.endswith("}"):
                candidates.append(cleaned)

    first = raw.find("{")
    last = raw.rfind("}")
    if first != -1 and last != -1 and last > first:
        candidates.append(raw[first : last + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue

    return None


def _validate_llm_decision(raw: dict, fallback: dict) -> tuple[str, str, str]:
    """Validate and normalize LLM verdict payload."""
    allowed_verdicts = {"APPROVED_AUTOMATICALLY", "REVIEW_MANUAL"}
    allowed_semaphores = {"GREEN", "AMBER", "RED"}

    verdict = str(raw.get("verdict", "")).strip().upper()
    semaphore = str(raw.get("semaphore", "")).strip().upper()
    reason = str(raw.get("reason", "")).strip()

    if verdict not in allowed_verdicts:
        verdict = fallback["verdict"]
    if semaphore not in allowed_semaphores:
        semaphore = fallback["semaphore"]
    if not reason:
        reason = fallback["reason"]

    return verdict, semaphore, reason[:320]


def _evaluate_metrics_with_llm(metrics: dict, run_trigger: str, fallback: dict) -> dict:
    """Use Gemini judge model to produce verdict/semaphore/reason from OCR signals."""
    levels = fallback["levels"]
    payload = _build_llm_payload(metrics, levels, run_trigger)

    prompt = (
        "You are an OCR quality judge for PDF to Markdown conversion. "
        "Given metrics and worst-page excerpts, decide whether output can be auto-approved or needs manual review.\n\n"
        "Return ONLY a JSON object with keys: verdict, semaphore, reason.\n"
        "Allowed verdict: APPROVED_AUTOMATICALLY or REVIEW_MANUAL.\n"
        "Allowed semaphore: GREEN, AMBER, RED.\n"
        "Use conservative judgment: if uncertainty or risk exists, choose REVIEW_MANUAL.\n"
        "Prefer RED for severe quality problems, AMBER for moderate risk, GREEN only when quality is clearly strong.\n\n"
        f"Input data:\n{json.dumps(payload, ensure_ascii=True)}"
    )

    start_time = time.perf_counter()
    response = judge_client.models.generate_content(
        model=settings.judge_model,
        contents=prompt,
    )
    latency_ms = (time.perf_counter() - start_time) * 1000.0
    text = response.text or ""
    parsed = _extract_json_object(text)
    if not parsed:
        raise ValueError("Judge model did not return parseable JSON")

    verdict, semaphore, reason = _validate_llm_decision(parsed, fallback)
    llm_decision = {
        "verdict": verdict,
        "semaphore": semaphore,
        "reason": reason,
        "run_trigger": run_trigger,
        "judge_model": settings.judge_model,
        "judge_mode": "llm",
        "cer_estimate": fallback["cer_estimate"],
        "wer_estimate": fallback["wer_estimate"],
        "levels": levels,
    }

    # Helpful traceability metadata for audits/debugging.
    llm_decision["judge_diagnostics"] = {
        "latency_ms": latency_ms,
        "input_summary": payload,
        "llm_output": parsed,
        "llm_text_excerpt": text[:1200],
    }
    return llm_decision


def evaluate_metrics(metrics: dict, run_trigger: str) -> dict:
    """Evaluate metrics with LLM judge; fall back to deterministic rules on failure."""
    fallback = _evaluate_metrics_rules(metrics, run_trigger)

    try:
        return _evaluate_metrics_with_llm(metrics, run_trigger, fallback)
    except Exception as error:
        logger.warning("LLM judge failed; using rules fallback: %s", error)
        fallback["judge_mode"] = "rules_fallback"
        fallback["reason"] = f"{fallback['reason']} (LLM fallback: {str(error)[:140]})"
        fallback["judge_diagnostics"] = {
            "fallback_error": str(error)[:500],
        }
        return fallback
