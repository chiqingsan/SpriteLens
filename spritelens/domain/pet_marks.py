"""紧凑体型/声音标记，与佩戴的纪念奖牌分开。"""


def size_mark(weight: int, weight_range) -> tuple[str, str] | None:
    low, high = weight_range
    if weight <= 0 or low <= 0 or high <= low:
        return None
    position = (weight - low) * 100
    width = high - low
    if position <= width * 2:
        return "小", "小不点"
    if position >= width * 98:
        return "大", "大块头"
    return None


def voice_mark(voice: int) -> tuple[str, str] | None:
    if -100 <= voice <= -96:
        return "粗", "粗嗓门"
    if 96 <= voice <= 100:
        return "婉", "婉转声"
    return None


def pet_marks(pet, weight_range) -> list[dict]:
    # 明确佩戴相应奖牌时优先采用；其它情况用竞品已核验的参考规则。
    worn = {1001: ("大", "大块头"), 1002: ("小", "小不点"),
            1025: ("粗", "粗嗓门"), 1026: ("婉", "婉转声")}.get(pet.worn_medal_id)
    size = size_mark(pet.weight, weight_range)
    voice = voice_mark(pet.voice)
    if worn:
        if worn[0] in ("大", "小"):
            size = worn
        else:
            voice = worn
    return [{"label": mark[0], "name": mark[1], "source": "worn" if worn == mark else "reference"}
            for mark in (size, voice) if mark]


__all__ = ["pet_marks", "size_mark", "voice_mark"]
