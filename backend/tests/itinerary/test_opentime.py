from app.itinerary.opentime import parse_opentime


def test_empty_or_allday_returns_full_window():
    assert parse_opentime("", 480) == (0, 480)
    assert parse_opentime("00:00-24:00", 480) == (0, 480)


def test_standard_range_shifts_to_0900_base():
    # 10:00-17:00 → 到达窗 = (10:00-09:00=60, 17:00-09:00=480)
    assert parse_opentime("10:00-17:00", 480) == (60, 480)


def test_open_before_0900_clamps_to_zero():
    # 08:30 开门 → 最早到达 0(不早于行程起点)
    lo, hi = parse_opentime("08:30-18:00", 480)
    assert lo == 0
    # 18:00 关门 → hi=540 分(以 09:00 为 0),不在此合并 day_budget(那是 VRPTW 独立约束)
    assert hi == 18 * 60 - 540  # 540


def test_close_before_0900_returns_full_window():
    # 关门(08:00)在行程起点 09:00 之前 → hi<=0 → 不约束
    assert parse_opentime("06:00-08:00", 480) == (0, 480)


def test_close_equals_open_returns_full_window():
    # 关门=开门(异常) → 不约束
    assert parse_opentime("12:00-12:00", 480) == (0, 480)


def test_takes_first_segment_of_multi():
    # 多段(午休)取第一段 09:00-12:00
    lo, hi = parse_opentime("09:00-12:00,14:00-18:00", 480)
    assert lo == 0
    assert hi == 12 * 60 - 540  # 180


def test_unparseable_returns_full_window():
    assert parse_opentime("全年无休", 480) == (0, 480)
    assert parse_opentime("周一至周五", 480) == (0, 480)
