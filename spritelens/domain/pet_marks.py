"""紧凑体型/声音标记，与佩戴的纪念奖牌分开。"""


def pet_marks(pet, weight_range) -> list[dict]:
    # 明确佩戴相应奖牌时优先采用；其它情况用竞品已核验的参考规则。
    worn = {1001: ("大", "大块头"), 1002: ("小", "小不点"),
            1025: ("粗", "粗嗓门"), 1026: ("婉", "婉转声")}.get(pet.worn_medal_id)
    low, high = weight_range
    size = None
    if pet.weight > 0 and low > 0 and high > low:
        position = (pet.weight - low) * 100
        if position <= (high - low) * 2:
            size = ("小", "小不点")
        elif position >= (high - low) * 98:
            size = ("大", "大块头")
    voice = ("粗", "粗嗓门") if -100 <= pet.voice <= -96 else ("婉", "婉转声") if 96 <= pet.voice <= 100 else None
    if worn:
        if worn[0] in ("大", "小"):
            size = worn
        else:
            voice = worn
    return [{"label": mark[0], "name": mark[1], "source": "worn" if worn == mark else "reference"}
            for mark in (size, voice) if mark]
