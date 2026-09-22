from app.cache import EvaluationCache


def test_expiry_and_false_value():
    now = [0.0]
    cache = EvaluationCache(2, 5, clock=lambda: now[0])
    _, generation = cache.get(("flag", "alice"))
    cache.put(("flag", "alice"), False, generation)
    assert cache.get(("flag", "alice"))[0] is False
    now[0] = 5
    assert cache.get(("flag", "alice"))[0] is None


def test_capacity_evicts_least_recently_used():
    cache = EvaluationCache(2, 5)
    cache.put(("flag", "alice"), True, 0)
    cache.put(("flag", "bob"), False, 0)
    cache.get(("flag", "alice"))
    cache.put(("flag", "carol"), True, 0)
    assert cache.get(("flag", "bob"))[0] is None
    assert cache.get(("flag", "alice"))[0] is True
    assert cache.get(("flag", "carol"))[0] is True


def test_invalidation_rejects_in_flight_old_read():
    cache = EvaluationCache(2, 5)
    _, old_generation = cache.get(("flag", "alice"))
    cache.invalidate()
    cache.put(("flag", "alice"), False, old_generation)
    assert cache.get(("flag", "alice"))[0] is None
    _, new_generation = cache.get(("flag", "alice"))
    cache.put(("flag", "alice"), True, new_generation)
    assert cache.get(("flag", "alice"))[0] is True
