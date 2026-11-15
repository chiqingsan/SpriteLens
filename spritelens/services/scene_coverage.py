"""本次运行的观察覆盖（世界格网）；与实时实体生命周期分开，不写场景 checkpoint。

覆盖记录「人物位置采样 + 观察半径」覆盖到的格：看得到多远的精灵，就记多少格。
半径由调用方明确提供，不用精灵位置外推——精灵会移动、
刷新，零实体不能证明空区。格索引使用绝对世界坐标 floor(raw / cell_size)，不依赖
具体地图的 origin，跨图、负坐标与后续投影调整都不需要重算已有格；行区间编码把
连续格压成 [gy, gx_start, run_len]，半径扩张后的格数增量仍然只占很小的载荷。

格按「世界所有者 + 地图」分桶：自己的世界（owner=0）长期保留，进入他人的世界
则换用另一个进度，避免把别人的世界当成自己走过的路；他人世界的进度从**开始记录**
起只保留 EXTERNAL_WORLD_TTL_SECONDS（3 天），到期后清除并在再次进入时重新记录。
所有者来自 0x0152 的 online_visiting_owner 与 0x0160 的 online_visit_owner，由调用方转入。
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
# 世界所有者 uid；0 表示自己的世界。
OWN_WORLD = 0
# 他人世界的覆盖进度从开始记录起只保留 3 天：到期后自动清除，再次进入时重新记录。
EXTERNAL_WORLD_TTL_SECONDS = 3 * 24 * 60 * 60


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
    owner: int = OWN_WORLD


class SceneCoverage:
    def __init__(self, cell_size: int = DEFAULT_CELL_SIZE_RAW, radius_raw: int = 0, *, enabled: bool = True, store: SceneCoverageStore | None = None, map_bounds: dict[int, tuple[int, int, int]] | None = None) -> None:
        self._uid = 0
        self._owner = OWN_WORLD
        self._enabled = enabled
        self._cell_size = max(1, int(cell_size))
        # 0 只记录采样所在格；正式应用传入独立的估计覆盖半径。
        self._radius_raw = max(0, int(radius_raw))
        self._store = store
        self._map_bounds = map_bounds
        # 桶键为 (世界所有者, 地图资源)；切换账号清空，切换世界只换当前桶。
        self._loaded: set[tuple[int, int]] = set()
        self._updated: dict[tuple[int, int], float] = {}
        # 他人世界的桶从第一次记录开始计时，到期即清除；自己的世界不参与。
        self._started: dict[tuple[int, int], float] = {}
        self._radii: dict[tuple[int, int], int] = {}
        self.error: str | None = None
        self._cells: dict[tuple[int, int], set[tuple[int, int]]] = {}
        self._row_cells: dict[tuple[int, int], dict[int, set[int]]] = {}
        self._row_runs: dict[tuple[int, int], dict[int, tuple[tuple[int, int, int], ...]]] = {}
        self._revisions: dict[tuple[int, int], int] = {}
        self._rows: dict[tuple[int, int], tuple[tuple[int, int, int], ...]] = {}
        if self._store is not None:
            # 启动时先清掉过期的他人世界记录，避免旧进度长期滞留在文件里。
            self._store.purge_expired(EXTERNAL_WORLD_TTL_SECONDS)

    @property
    def cell_size(self) -> int:
        return self._cell_size

    @property
    def world_owner(self) -> int:
        return self._owner

    def select_account(self, uid: int) -> None:
        if uid != self._uid:
            self._uid = uid
            self._owner = OWN_WORLD
            self._drop_all()
            self.error = None

    def select_owner(self, owner: int) -> bool:
        """切换当前世界所有者；返回是否变化，未变化时不动缓存。"""
        value = owner if type(owner) is int and owner > 0 else OWN_WORLD
        if value == self._owner:
            return False
        self._owner = value
        self.error = None
        return True

    def _key(self, resource: int) -> tuple[int, int]:
        return (self._owner, resource)

    def _drop(self, key: tuple[int, int]) -> None:
        self._cells.pop(key, None)
        self._row_cells.pop(key, None)
        self._row_runs.pop(key, None)
        self._revisions.pop(key, None)
        self._rows.pop(key, None)
        self._updated.pop(key, None)
        self._started.pop(key, None)
        self._radii.pop(key, None)
        self._loaded.discard(key)

    def _drop_all(self) -> None:
        self._cells.clear()
        self._row_cells.clear()
        self._row_runs.clear()
        self._revisions.clear()
        self._rows.clear()
        self._updated.clear()
        self._started.clear()
        self._radii.clear()
        self._loaded.clear()

    def _expired(self, key: tuple[int, int], now: float) -> bool:
        """他人世界的桶从开始记录起超过保留期即视为过期；自己的世界不过期。"""
        if key[0] == OWN_WORLD:
            return False
        started = self._started.get(key)
        return started is not None and now - started > EXTERNAL_WORLD_TTL_SECONDS

    def _expire_stale(self, resource: int, now: float | None = None) -> None:
        key = self._key(resource)
        if not self._expired(key, time.time() if now is None else now):
            return
        # 到期后清除，下一次采样从零开始重新计时。
        self._drop(key)
        self._loaded.add(key)
        if self._store is not None and self._uid > 0:
            self._store.put(self._uid, resource, None, key[0])

    def purge_expired(self, now: float | None = None) -> int:
        """清除已到期（从开始记录起超过保留期）的他人世界桶；返回清除的桶数。"""
        current = time.time() if now is None else now
        expired = [key for key in list(set(self._started) | set(self._cells)) if self._expired(key, current)]
        for key in expired:
            self._drop(key)
            self._loaded.add(key)
            if self._store is not None and self._uid > 0:
                self._store.put(self._uid, key[1], None, key[0])
        return len(expired)

    def _load(self, resource: int) -> None:
        key = self._key(resource)
        if key in self._loaded or self._store is None or self._uid <= 0:
            return
        raw = self._store.load(self._uid, resource, key[0])
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
            self._cells[key] = cells
            by_row: dict[int, set[int]] = {}
            for gy, gx in cells:
                by_row.setdefault(gy, set()).add(gx)
            self._row_cells[key] = by_row
            self._revisions[key] = 1
            self._updated[key] = raw["updated_at"]
            # 旧记录没有开始记录时间时按最近写入时间估算，避免读入后立刻被误删。
            started = raw.get("started_at", raw["updated_at"])
            self._started[key] = started if isinstance(started, (int, float)) else raw["updated_at"]
            self._radii[key] = raw["radius"]
        self._loaded.add(key)
        if raw is not None:
            # 开始记录时间超过保留期的他人世界历史不再恢复，直接从记录中清除。
            self._expire_stale(resource)

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
        self._expire_stale(resource)
        key = self._key(resource)
        if key in self._radii and self._radii[key] != self._radius_raw:
            self.error = "记录半径已变化，请清除当前地图后开始新一轮"
            return False
        cells = self._cells.get(key, set())
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
        self._cells[key] = cells
        by_row = self._row_cells.setdefault(key, {})
        runs = self._row_runs.setdefault(key, {})
        for gy, gx in new:
            by_row.setdefault(gy, set()).add(gx)
            runs.pop(gy, None)
        self._revisions[key] = self._revisions.get(key, 0) + 1
        # 行区间按需重算：只有新增格才失效，读快照不反复排序。
        self._rows.pop(key, None)
        now = time.time()
        # 他人世界的保留期从第一次记录开始算，之后继续记录不会延长它。
        self._started.setdefault(key, now)
        self._updated[key] = now
        self._radii[key] = self._radius_raw
        self.error = None
        if self._store is not None:
            snap = self.snapshot(resource)
            self._store.put(self._uid, resource, {"coordinate_version": 1, "cell_size": self._cell_size,
                "radius": self._radius_raw, "updated_at": snap.updated_at,
                "started_at": self._started[key], "rows": [list(row) for row in snap.rows]}, key[0])
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
        """清空当前世界指定地图的足迹；resource 为 None 时清空当前世界的全部地图。"""
        owner = self._owner
        if resource is None:
            targets = sorted({key for bucket in (self._cells, self._loaded, self._updated) for key in bucket if key[0] == owner})
        else:
            targets = [(owner, resource)]
        for key in targets:
            self._drop(key)
            # 内存清空后不再从文件恢复同一份历史。
            self._loaded.add(key)
        if self._store is not None and self._uid > 0:
            for key in targets:
                self._store.put(self._uid, key[1], None, key[0])
        self.error = None

    def snapshot(self, resource: int | None) -> CoverageSnapshot | None:
        """无资源或无格时返回 None：没有有效数据就不画覆盖，也不用空集合占位。"""
        if resource is None or (self._map_bounds is not None and resource not in self._map_bounds):
            return None
        self._load(resource)
        self._expire_stale(resource)
        key = self._key(resource)
        cells = self._cells.get(key)
        if not cells:
            return None
        return CoverageSnapshot(
            self._cell_size,
            self._revisions.get(key, 0),
            self._rows_for(resource),
            len(cells),
            self._updated.get(key),
            self._store is not None,
            self._radii.get(key, self._radius_raw),
            key[0],
        )

    def unavailable_reason(self, resource: int | None) -> str | None:
        if (resource is not None and self._map_bounds is not None and resource not in self._map_bounds
                and self._store is not None and self._uid > 0 and self._store.load(self._uid, resource, self._owner) is not None):
            return "地图或坐标版本不可用，历史搜索记录已保留但暂不显示"
        return None

    def _rows_for(self, resource: int) -> tuple[tuple[int, int, int], ...]:
        key = self._key(resource)
        cached = self._rows.get(key)
        if cached is not None:
            return cached
        by_row = self._row_cells[key]
        cached_runs = self._row_runs.setdefault(key, {})
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
        self._rows[key] = result
        return result
