"""Shared schedule category vocabulary and presentation metadata."""

CATEGORIES = (
    ("업무", "sky"),
    ("개인", "mint"),
    ("중요", "peach"),
    ("학습", "vanilla"),
    ("기타", "lavender"),
)

# 키에서 이름으로.  dict(CATEGORIES)는 이름에서 키로 가는 반대 방향이라,
# category_name('sky')가 '일정'을 돌려주고 있었다.
CATEGORY_NAMES = {key: name for name, key in CATEGORIES}
CATEGORY_COLORS = {
    "sky": ("#E7F0FF", "#234F9A"),
    "mint": ("#E4F8EE", "#176448"),
    "peach": ("#FFE9E7", "#9C3D37"),
    "vanilla": ("#FFF4D6", "#815B10"),
    "lavender": ("#F0EAFE", "#6042A6"),
}


def category_name(value: object) -> str:
    return CATEGORY_NAMES.get(str(value), "일정")

