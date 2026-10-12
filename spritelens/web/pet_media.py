"""稳定物种 ID 的官方头像/立绘映射；缺图不借用其它物种。"""
from functools import lru_cache
import json
from spritelens.paths import static_dir


@lru_cache(maxsize=1)
def _index() -> dict:
    path = static_dir() / "pet_media.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def pet_images(base_id: int, shiny: bool = False) -> dict:
    entry = _index().get(str(base_id), {})
    normal = entry.get("normal", {})
    selected = entry.get("shiny", {}) if shiny else normal
    return {"portrait_url": selected.get("portrait") or normal.get("portrait") or "",
            "artwork_url": selected.get("artwork") or normal.get("artwork") or f"/static/pets/{base_id}.webp"}
