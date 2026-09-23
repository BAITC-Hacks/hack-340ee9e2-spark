"""Conservative attribution using time intervals, without altering transcript text."""

from copy import deepcopy
import math
import re


def _interval(item):
    start, end = float(item['start']), float(item['end'])
    if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end):
        raise ValueError('Некорректный временной интервал.')
    return start, end


def align_segments(segments: list[dict], turns: list[dict]) -> tuple[list[dict], list[dict]]:
    """Preserve all fields, updating only speaker; return separate diagnostics.

    Any detected multi-speaker overlap or speaker change is ambiguous without
    word timestamps. Require at least 50% segment coverage for a single speaker.
    Coverage is a time fraction, NOT a model confidence score.
    """
    clean_turns = []
    for turn in turns:
        start, end = _interval(turn)
        speaker = turn['speaker']
        if not isinstance(speaker, str) or not re.fullmatch(r'SPEAKER_\d{2,}', speaker):
            raise ValueError('Ожидалась техническая метка SPEAKER_00.')
        clean_turns.append((start, end, speaker))
    output = deepcopy(segments)
    assignments = []
    for index, segment in enumerate(output):
        start, end = _interval(segment)
        clipped = [(max(start, a), min(end, b), sp) for a, b, sp in clean_turns
                   if min(end, b) > max(start, a)]
        points = sorted({start, end, *(p for a, b, _ in clipped for p in (a, b))})
        coverage = {}
        overlap_seconds = 0.0
        for a, b in zip(points, points[1:]):
            active = {sp for lo, hi, sp in clipped if lo < b and hi > a}
            for speaker in active:
                coverage[speaker] = coverage.get(speaker, 0.0) + b - a
            if len(active) > 1:
                overlap_seconds += b - a
        segment['speaker'] = None
        if not coverage:
            reason = 'no_matching_speech'
        elif overlap_seconds > 1e-6:
            reason = 'overlapping_speech'
        elif len(coverage) > 1:
            reason = 'speaker_change_within_segment'
        else:
            speaker, seconds = next(iter(coverage.items()))
            if seconds / (end - start) < 0.5:
                reason = 'insufficient_coverage'
            else:
                segment['speaker'] = speaker
                reason = 'assigned'
        assignments.append({
            'segment_index': index, 'reason': reason,
            'candidates': sorted(coverage),
            'coverage_seconds': {sp: round(n, 6) for sp, n in sorted(coverage.items())},
            'overlap_seconds': round(overlap_seconds, 6),
        })
    return output, assignments
