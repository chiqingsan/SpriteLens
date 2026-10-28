"""本次运行的观察覆盖（世界格网）；与实时实体生命周期分开，不写场景 checkpoint。

覆盖记录「人物位置采样 + 观察半径」覆盖到的格：看得到多远的精灵，就记多少格。
半径由调用方明确提供，不用精灵位置外推——精灵会移动、
刷新，零实体不能证明空区。格索引使用绝对世界坐标 floor(raw / cell_size)，不依赖
具体地图的 origin，跨图、负坐标与后续投影调整都不需要重算已有格；行区间编码把
连续格压成 [gy, gx_start, run_len]，半径扩张后的格数增量仍然只占很小的载荷。
"""
from __future__ import annotations

from dataclasses import dataclass
import time
from spritelens.repositories.scene_coverage_store import SceneCoverageStore

# 世界格边长（原始坐标单位）。2000 是待现场确认的分辨率上限，对应约
# 204×204 格的大陆；实现见 docs/NEARBY_MAP_PLAN_2026-10-26.md §6.4。
DEFAULT_CELL_SIZE_RAW = 2000
# 单账号单地图的格数上限；超出后拒绝新格但保留已有记录，避免无界内存。
MAX_CELLS = 65536


@dataclass(frozen=True)
class CoverageSnapshot:
    """只含格索引的覆盖摘要；行区间编码把连续格压成 [gy, gx_start, run_len]。"""
    cell_size: int
    revision: int
    rows: tuple[tuple[int, int, int], ...]
    cells: int
    updated_at: float | None = None
    persistent: bool = False
    radius: int = 0


class SceneCoverage:
    def __init__(self, cell_size: int = DEFAULT_CELL_SIZE_RAW, radius_raw: int = 0, *, enabled: bool = True, store: SceneCoverageStore | None = None, map_bounds: dict[int, tuple[int, int, int]] | None = None) -> None:
        self._uid = 0
        self._enabled = enabled
        self._cell_size = max(1, int(cell_size))
        # 0 只记录采样所在格；正式应用传入独立的估计覆盖半径。
        self._radius_raw = max(0, int(radius_raw))
        self._store = store
        self._map_bounds = map_bounds
        self._loaded: set[int] = set()
        self._updated: dict[int, float] = {}
        self._radii: dict[int, int] = {}
        self.error: str | None = None
        self._cells: dict[int, set[tuple[int, int]]] = {}
        self._row_cells: dict[int, dict[int, set[int]]] = {}
        self._row_runs: dict[int, dict[int, tuple[tuple[int, int, int], ...]]] = {}
        self._revisions: dict[int, int] = {}
        self._rows: dict[int, tuple[tuple[int, int, int], ...]] = {}

    @property
    def cell_size(self) -> int:
        return self._cell_size

    def select_account(self, uid: int) -> None:
        if uid != self._uid:
            self._uid = uid
            self._cells.clear()
            self._row_cells.clear()
            self._row_runs.clear()
            self._revisions.clear()
            self._rows.clear()
            self._loaded.clear()
            self._updated.clear()
            self._radii.clear()
            self.error = None

    def _load(self, resource: int) -> None:
        if resource in self._loaded or self._store is None or self._uid <= 0:
            return
        raw = self._store.load(self._uid, resource)
        if raw is not None:
            if (raw.get("coordinate_version") != 1 or raw.get("cell_size") != self._cell_size
                    or type(raw.get("radius")) is not int or raw["radius"] < 0
                    or not isinstance(raw.get("updated_at"), (int, float)) or not isinstance(raw.get("rows"), list)):
                raise ValueError("搜索覆盖记录版本或格式不兼容，原文件已保留")
            cells: set[tuple[int, int]] = set()
            for row in raw["rows"]:
                if (not isinstance(row, list) or len(row) != 3 or any(type(n) is not int for n in row)
                        or row[2] <= 0 or len(cells) + row[2] > MAX_CELLS):
                    raise ValueError("搜索覆盖格格式无效，原文件已保留")
                cells.update((row[0], x) for x in range(row[1], row[1] + row[2]))
            self._cells[resource] = cells
            by_row: dict[int, set[int]] = {}
            for gy, gx in cells:
                by_row.setdefault(gy, set()).add(gx)
            self._row_cells[resource] = by_row
            self._revisions[resource] = 1
            self._updated[resource] = raw["updated_at"]
            self._radii[resource] = raw["radius"]
        self._loaded.add(resource)

    def record(self, resource: int | None, point: tuple[int | None, ...] | None) -> bool:
        """把采样点及其观察半径覆盖到的格记为已记录；返回是否产生了新格。"""
        if not self._enabled or resource is None or point is None or len(point) < 2:
            return False
        x, y = point[0], point[1]
        # 协议解包可能给出 None；坐标必须是整数才写格，非数字一律丢弃。
        if not isinstance(x, int) or not isinstance(y, int) or isinstance(x, bool) or isinstance(y, bool):
            return False
        bounds = self._map_bounds.get(resource) if self._map_bounds is not None else None
        if self._map_bounds is not None and bounds is None:
            return False
        if bounds is not None:
            ox, oy, side = bounds
            if not (ox <= x < ox + side and oy <= y < oy + side):
                return False
        self._load(resource)
        if resource in self._radii and self._radii[resource] != self._radius_raw:
            self.error = "记录半径已变化，请清除当前地图后开始新一轮"
            return False
        cells = self._cells.get(resource, set())
        try:
            new = [cell for cell in self._cells_for(x, y) if cell not in cells and (
                bounds is None or (cell[1] * self._cell_size < bounds[0] + bounds[2]
                    and (cell[1] + 1) * self._cell_size > bounds[0]
                    and cell[0] * self._cell_size < bounds[1] + bounds[2]
                    and (cell[0] + 1) * self._cell_size > bounds[1]))]
        except ValueError as exc:
            self.error = str(exc)
            return False
        # 到上限后整次采样都不写入，避免出现半个圆；已记录的格保留。
        if len(cells) + len(new) > MAX_CELLS:
            self.error = "搜索覆盖已达到容量上限，无法继续记录"
            return False
        if not new:
            return False
        cells.update(new)
        self._cells[resource] = cells
        by_row = self._row_cells.setdefault(resource, {})
        runs = self._row_runs.setdefault(resource, {})
        for gy, gx in new:
            by_row.setdefault(gy, set()).add(gx)
            runs.pop(gy, None)
        self._revisions[resource] = self._revisions.get(resource, 0) + 1
        # 行区间按需重算：只有新增格才失效，读快照不反复排序。
        self._rows.pop(resource, None)
        self._updated[resource] = time.time()
        self._radii[resource] = self._radius_raw
        self.error = None
        if self._store is not None:
            snap = self.snapshot(resource)
            self._store.put(self._uid, resource, {"coordinate_version": 1, "cell_size": self._cell_size,
                "radius": self._radius_raw, "updated_at": snap.updated_at, "rows": [list(row) for row in snap.rows]})
        return True

    def _cells_for(self, x: int, y: int) -> list[tuple[int, int]]:
        """采样点与观察半径覆盖到的格；格矩形与圆相交（含相切）即算。"""
        size = self._cell_size
        # Python 的 // 对负数向下取整，与计划里的 floor 语义一致。
        center = (y // size, x // size)
        radius = self._radius_raw
        if radius <= 0:
            return [center]
        # 圆的左/上边界恰落在格线上时，另一侧的格也与圆相切。
        gx0, gx1 = (x - radius - 1) // size, (x + radius) // size
        gy0, gy1 = (y - radius - 1) // size, (y + radius) // size
        # 不得静默退化为仅记录中心格。
        if (gx1 - gx0 + 1) * (gy1 - gy0 + 1) > MAX_CELLS:
            raise ValueError("搜索覆盖半径过大，不能安全计算")
        limit = radius * radius
        found: list[tuple[int, int]] = []
        for gy in range(gy0, gy1 + 1):
            top, bottom = gy * size, (gy + 1) * size
            dy = 0 if top <= y <= bottom else min(abs(y - top), abs(y - bottom))
            for gx in range(gx0, gx1 + 1):
                left, right = gx * size, (gx + 1) * size
                dx = 0 if left <= x <= right else min(abs(x - left), abs(x - right))
                if dx * dx + dy * dy <= limit:
                    found.append((gy, gx))
        return found

    def clear(self, resource: int | None = None) -> None:
        """清空指定地图的足迹；resource 为 None 时清空全部地图。"""
        if resource is None:
            self._cells.clear()
            self._row_cells.clear()
            self._row_runs.clear()
            self._revisions.clear()
            self._rows.clear()
            return
        self._cells.pop(resource, None)
        self._row_cells.pop(resource, None)
        self._row_runs.pop(resource, None)
        self._revisions.pop(resource, None)
        self._rows.pop(resource, None)
        self._updated.pop(resource, None)
        self._radii.pop(resource, None)
        self._loaded.add(resource)
        self.error = None
        if self._store is not None and self._uid > 0:
            self._store.put(self._uid, resource, None)

    def snapshot(self, resource: int | None) -> CoverageSnapshot | None:
        """无资源或无格时返回 None：没有有效数据就不画覆盖，也不用空集合占位。"""
        if resource is None or (self._map_bounds is not None and resource not in self._map_bounds):
            return None
        self._load(resource)
        cells = self._cells.get(resource)
        if not cells:
            return None
        return CoverageSnapshot(
            self._cell_size,
            self._revisions.get(resource, 0),
            self._rows_for(resource),
            len(cells),
            self._updated.get(resource),
            self._store is not None,
            self._radii.get(resource, self._radius_raw),
        )

    def unavailable_reason(self, resource: int | None) -> str | None:
        if (resource is not None and self._map_bounds is not None and resource not in self._map_bounds
                and self._store is not None and self._uid > 0 and self._store.load(self._uid, resource) is not None):
            return "地图或坐标版本不可用，历史搜索记录已保留但暂不显示"
        return None

    def _rows_for(self, resource: int) -> tuple[tuple[int, int, int], ...]:
        cached = self._rows.get(resource)
        if cached is not None:
            return cached
        by_row = self._row_cells[resource]
        cached_runs = self._row_runs.setdefault(resource, {})
        rows: list[tuple[int, int, int]] = []
        for gy in sorted(by_row):
            if gy in cached_runs:
                rows.extend(cached_runs[gy])
                continue
            columns = sorted(by_row[gy])
            row_runs: list[tuple[int, int, int]] = []
            start = previous = columns[0]
            for gx in columns[1:]:
                if gx == previous + 1:
                    previous = gx
                    continue
                row_runs.append((gy, start, previous - start + 1))
                start = previous = gx
            row_runs.append((gy, start, previous - start + 1))
            cached_runs[gy] = tuple(row_runs)
            rows.extend(row_runs)
        result = tuple(rows)
        self._rows[resource] = result
        return result
