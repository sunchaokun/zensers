"""Deterministic chapter coverage checks used before and after writing."""

from typing import Any, Dict, Iterable, List

from .models import ChapterCoverage, ChapterRequirement, ReportEvidenceContext


class ChapterCoverageChecker:
    def check(
        self,
        requirement: ChapterRequirement,
        chapter_data: Dict[str, Any],
        context: ReportEvidenceContext,
    ) -> ChapterCoverage:
        structured_text = self._text(chapter_data)
        raw_items = context.raw_search_results or []
        raw_text = "\n".join(self._text(item) for item in raw_items)

        available_structured = [
            metric for metric in requirement.required_metrics
            if metric.lower() in structured_text.lower()
            or any(str(dp.get("metric", "")).lower() == metric.lower()
                   for dp in chapter_data.get("upstream_data_points", [])
                   if isinstance(dp, dict))
        ]
        available_raw = [
            metric for metric in requirement.required_metrics
            if metric.lower() in raw_text.lower()
            and any(
                self._usable_evidence(item)
                and metric.lower() in self._text(item).lower()
                for item in raw_items
            )
            and metric not in available_structured
        ]
        missing_metrics = [
            metric for metric in requirement.required_metrics
            if metric not in available_structured and metric not in available_raw
        ]
        missing_topics = [
            topic for topic in requirement.required_topics
            if topic.lower() not in structured_text.lower()
            and not any(
                self._usable_evidence(item)
                and topic.lower() in self._text(item).lower()
                for item in raw_items
            )
        ]
        return ChapterCoverage(
            ready_to_write=not missing_metrics and not missing_topics,
            missing_topics=missing_topics,
            missing_metrics=missing_metrics,
            available_in_structured=available_structured,
            available_in_raw_search=available_raw,
            external_search_required=bool(missing_metrics or missing_topics),
        )

    @staticmethod
    def _usable_evidence(item: Dict[str, Any]) -> bool:
        return bool(
            str(item.get("url") or item.get("href") or "").strip()
            and (
                str(item.get("evidence_id") or "").strip()
                or str(item.get("evidence_excerpt") or item.get("excerpt") or "").strip()
                or str(item.get("snippet") or "").strip()
            )
        )

    @staticmethod
    def _text(value: Any) -> str:
        if isinstance(value, dict):
            return " ".join(ChapterCoverageChecker._text(v) for v in value.values())
        if isinstance(value, (list, tuple, set)):
            return " ".join(ChapterCoverageChecker._text(v) for v in value)
        return str(value or "")
