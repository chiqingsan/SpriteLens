"""稳定物种 ID 的官方头像/立绘映射；缺图不借用其它物种，只有登记过的同画别名例外。"""
from functools import lru_cache
import json
from spritelens.paths import static_dir

# 同画别名：这些 40xx 变体在官方 CDN 与 nrc wiki 都没有独立头像文件，但 wiki 头像与
# 同族 50xx 官方头像经像素比对（统一白底 64×64，平均绝对差 1.17–1.70/255，与对照组
# 3001 的 1.03 同量级）证明是同一张画。只登记有该证据的条目，不按名称或 dex 猜测；
# 4076 伊里斯没有可复用的同类资源，保持首字占位。
_MEDIA_ALIASES = {4012: 5006, 4019: 5004, 4079: 5001, 4086: 5023}


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
    variant = "shiny" if shiny else "normal"
    # 没有独立素材时回落到同画别名的官方 256 webp；别名同样不存在时才由调用方显示占位。
    media_id = base_id if entry or base_id not in _MEDIA_ALIASES else _MEDIA_ALIASES[base_id]
    return {"portrait_url": selected.get("portrait") or normal.get("portrait") or
            (f"/static/pet-media/{media_id}-{variant}-portrait.webp" if media_id > 0 else ""),
            "artwork_url": selected.get("artwork") or normal.get("artwork") or
            (f"/static/pet-media/{media_id}-{variant}-artwork.webp" if media_id > 0 else "")}
