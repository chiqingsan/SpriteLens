"""家园与本地配窝共用的逐父母性格参考，不是实测成功率。"""
from __future__ import annotations


def parent_nature_reference(male: str | None, female: str | None, *, male_academy: bool = False,
                            female_academy: bool = False) -> dict:
    if male_academy and female_academy:
        participants = ((female if male == female else None, 1.0),)
    elif female_academy:
        participants = ((female, 1.0),)
    elif male_academy:
        participants = ((male, 1.0),)
    else:
        participants = ((male, .3), (female, .3))
    known: dict[str, float] = {}
    unknown = 0.0
    for nature, share in participants:
        if nature:
            known[nature] = known.get(nature, 0) + share
        else:
            unknown += share
    return {"known": known, "unknown": unknown, "random": .4 if len(participants) == 2 else 0}
