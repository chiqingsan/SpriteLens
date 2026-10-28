"""紧凑体型/声音标记，与佩戴的纪念奖牌分开。"""


def size_mark(weight: int, weight_range) -> tuple[str, str] | None:
    low, high = weight_range
    if low <= 0 or high <= low or not low <= weight <= high:
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


def egg_voice(mother_voice: int, father_voice: int) -> int:
    """蛋的声音遗传：父母本声音取平均并向下取整（实测规则）。"""
    return (mother_voice + father_voice) // 2


def voice_tags(voice: int) -> tuple[str, ...]:
    """声音值可打上的参考标签：婉转声/粗嗓门，满值再带满分/底分。"""
    tags: list[str] = []
    sound = voice_mark(voice)
    if sound is not None:
        tags.append(sound[1])
    if voice == 100:
        tags.append("满分")
    elif voice == -100:
        tags.append("底分")
    return tuple(tags)


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


def observation_marks(weight: int | None, voice: int | None, weight_range) -> list[dict]:
    """Return compact marks that can be derived from a live scene observation."""
    marks = []
    if weight is not None:
        size = size_mark(weight, weight_range)
        if size:
            marks.append({"label": size[0], "name": size[1], "source": "reference"})
        low, high = weight_range
        if high > low > 0 and weight == low:
            marks.append({"label": "底重", "name": "底重", "source": "reference"})
        elif high > low > 0 and weight == high:
            marks.append({"label": "满重", "name": "满重", "source": "reference"})
    if voice is not None:
        sound = voice_mark(voice)
        if sound:
            marks.append({"label": sound[0], "name": sound[1], "source": "reference"})
        if voice == -100:
            marks.append({"label": "底分", "name": "底分", "source": "reference"})
        elif voice == 100:
            marks.append({"label": "满分", "name": "满分", "source": "reference"})
    return marks


__all__ = ["egg_voice", "observation_marks", "pet_marks", "size_mark", "voice_mark", "voice_tags"]
