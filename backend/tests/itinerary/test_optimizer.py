from app.itinerary.optimizer import solve_vrptw


def _matrix():
    # 0=depot, 1..4 景点；西簇(1,2) 东簇(3,4)
    return [
        [0, 10, 12, 40, 42],
        [10, 0, 5, 38, 40],
        [12, 5, 0, 36, 38],
        [40, 38, 36, 0, 6],
        [42, 40, 38, 6, 0],
    ]


def test_two_days_groups_geographically():
    nodes = [{"visit_minutes": 0}] + [{"visit_minutes": 60} for _ in range(4)]
    routes, dropped, relax = solve_vrptw(_matrix(), nodes, days=2, day_budget=480)
    assert len(routes) == 2
    assert dropped == []
    assert relax == 0
    # 西簇{1,2} 与 东簇{3,4} 各自同天(不跨簇拆分)
    flat = [set(r) for r in routes if r]
    assert {1, 2} in flat or {2, 1} in flat
    assert {3, 4} in flat or {4, 3} in flat


def test_high_rating_kept_over_low_when_budget_tight():
    # 5 景点但每天预算只够 2 个；高分必留、低分被丢
    nodes = [{"visit_minutes": 0}] + [{"visit_minutes": 200} for _ in range(5)]
    ratings = [0.0, 5.0, 5.0, 4.8, 1.0, 1.0]
    mat = [[0]*6] + [[10]*6 for _ in range(5)]
    for i in range(6):
        mat[i][i] = 0
    routes, dropped, relax = solve_vrptw(mat, nodes, days=1, day_budget=480,
                                         ratings=ratings)
    visited = {x for r in routes for x in r}
    # 高分(1,2)应在，低分(4,5)更可能被丢
    assert 1 in visited and 2 in visited
    assert len(dropped) >= 1


def test_balances_across_days_no_empty_day():
    # 4 景点 2 天，总时间预算足够全塞一天；均衡约束应把点摊开，不留空天
    nodes = [{"visit_minutes": 0}] + [{"visit_minutes": 60} for _ in range(4)]
    routes, dropped, relax = solve_vrptw(_matrix(), nodes, days=2, day_budget=480)
    assert dropped == []
    # 每天都被用上（无空天）
    assert all(len(r) >= 1 for r in routes)
    # 每天最多 ceil(4/2)=2 个点
    assert all(len(r) <= 2 for r in routes)


def test_relax_when_time_windows_infeasible():
    nodes = [{"visit_minutes": 0}] + [{"visit_minutes": 60} for _ in range(3)]
    mat = [[0]*4] + [[10]*4 for _ in range(3)]
    for i in range(4):
        mat[i][i] = 0
    # 全冲突窗：每个点只能 10~11 分钟到达，互斥 → L0 无解
    tw = [(0, 480), (10, 11), (10, 11), (10, 11)]
    routes, dropped, relax = solve_vrptw(mat, nodes, days=1, day_budget=480,
                                         time_windows=tw)
    assert relax >= 1            # 放松过
    visited = {x for r in routes for x in r}
    assert len(visited) >= 1     # 放松后能排进点
