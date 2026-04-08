"""Rule-based judge for OCR quality decisions."""
import random
from config.settings import settings


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


def evaluate_metrics(metrics: dict, run_trigger: str) -> dict:
    """Evaluate metrics and return a decision payload."""
    similarity = metrics.get("average_similarity")
    if not isinstance(similarity, float):
        similarity = None

    cer_estimate = None if similarity is None else max(0.0, 1.0 - similarity)
    wer_estimate = None if similarity is None else max(0.0, 1.0 - (similarity * 0.98))

    similarity_level, similarity_note = _level_similarity(similarity)
    cer_level, cer_note = _level_cer(cer_estimate)
    structural_level, structural_note = _level_similarity(similarity)

    levels = [
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
        "cer_estimate": cer_estimate,
        "wer_estimate": wer_estimate,
        "levels": levels,
    }
