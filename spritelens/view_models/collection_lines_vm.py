"""双牌产线页面状态：展示候选与缺口，保留完整目录的统计分母。"""
from __future__ import annotations

from dataclasses import dataclass

from spritelens.domain.collection_lines import CollectionGoal
from spritelens.services.collection_lines_service import CollectionLinesService, CollectionSnapshot


@dataclass(frozen=True)
class CollectionView:
    snapshot: CollectionSnapshot
    totals: dict[str, int]


class CollectionLinesViewModel:
    def __init__(self, service: CollectionLinesService) -> None:
        self._service = service

    def snapshot(self, goal: CollectionGoal) -> CollectionView:
        snapshot = self._service.snapshot(goal)
        counts = {status: sum(line.status == status for line in snapshot.lines)
                  for status in ("collected", "missingMale", "missing", "unknown")}
        counts["eligible"] = len(snapshot.lines) - counts["unknown"]
        counts["complete"] = counts["collected"] + (counts["missingMale"] if goal.ignore_missing_male else 0)
        return CollectionView(snapshot, counts)
