from app.core import constants


def test_constants_present_and_sane():
    assert constants.SOLVE_TIME_LIMIT_S > 0
    assert constants.CANDIDATE_MULTIPLIER >= 1.0
    assert constants.PER_DAY_CAP >= 1
    assert constants.MATRIX_CONCURRENCY >= 1
    assert constants.MATRIX_CACHE_TTL_DAYS >= 1
    assert constants.WALK_KM < constants.TRANSIT_KM
    assert constants.RELAX_BUDGET_FACTOR > 1.0


def test_ortools_importable():
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2  # noqa: F401
