"""Pure graph/optimization tests -- no Django, no DB, no mock_bpp server. Crafted small
graphs prove the leg-graph search actually composes multi-leg itineraries and that
rank_itineraries genuinely trades cost off against time, not just returns whatever
enumeration order find_itinerary_paths happens to produce."""
from trip_planner.planner import LegOption, build_graph, find_itinerary_paths, rank_itineraries


def _leg(from_place, to_place, fare, duration_minutes, mode="test"):
    return LegOption(from_place=from_place, to_place=to_place, fare=fare, duration_minutes=duration_minutes, mode=mode)


def test_build_graph_makes_every_leg_usable_in_both_directions():
    graph = build_graph([_leg("A", "B", 100, 10)])

    assert [leg.to_place for leg in graph["A"]] == ["B"]
    assert [leg.to_place for leg in graph["B"]] == ["A"]


def test_find_itinerary_paths_finds_the_direct_single_leg_route():
    graph = build_graph([_leg("A", "B", 100, 10)])

    paths = find_itinerary_paths(graph, "A", "B")

    assert len(paths) == 1
    assert [leg.to_place for leg in paths[0]] == ["B"]


def test_find_itinerary_paths_finds_a_multi_leg_route_through_an_intermediate_place():
    graph = build_graph([_leg("A", "HUB", 50, 10), _leg("HUB", "B", 50, 10)])

    paths = find_itinerary_paths(graph, "A", "B")

    assert len(paths) == 1
    assert [leg.to_place for leg in paths[0]] == ["HUB", "B"]


def test_find_itinerary_paths_finds_every_alternative_route():
    """Direct A->B, plus a 2-leg A->HUB->B alternative -- both real, independent options
    a traveller could actually take, exactly BUILD_PLAN.md's "2-3 ranked itinerary
    options" scenario."""
    graph = build_graph([
        _leg("A", "B", 3000, 60),          # fast, direct, expensive
        _leg("A", "HUB", 100, 30),         # cheap, slower, 2 legs
        _leg("HUB", "B", 100, 30),
    ])

    paths = find_itinerary_paths(graph, "A", "B")

    leg_sequences = {tuple(leg.to_place for leg in path) for path in paths}
    assert leg_sequences == {("B",), ("HUB", "B")}


def test_find_itinerary_paths_never_revisits_a_place_within_one_itinerary():
    """A triangle A-B-C-A must not produce a path that loops back through an
    already-visited place -- these are simple paths, not walks."""
    graph = build_graph([_leg("A", "B", 10, 5), _leg("B", "C", 10, 5), _leg("C", "A", 10, 5)])

    paths = find_itinerary_paths(graph, "A", "C", max_legs=4)

    for path in paths:
        places_visited = ["A"] + [leg.to_place for leg in path]
        assert len(places_visited) == len(set(places_visited))


def test_find_itinerary_paths_respects_the_max_legs_cap():
    graph = build_graph([_leg("A", "B", 10, 5), _leg("B", "C", 10, 5), _leg("C", "D", 10, 5)])

    paths = find_itinerary_paths(graph, "A", "D", max_legs=2)

    assert paths == []  # the only route A->B->C->D needs 3 legs


def test_find_itinerary_paths_returns_nothing_for_an_unconnected_destination():
    graph = build_graph([_leg("A", "B", 10, 5)])

    assert find_itinerary_paths(graph, "A", "Nowhere") == []


def test_rank_itineraries_puts_the_cheapest_option_first_when_cost_is_all_that_matters():
    """The exact scenario this module exists for: a 2-leg itinerary that's 30x cheaper
    but 2x slower must outrank a 1-leg direct route when cost_weight dominates."""
    cheap_slow = (_leg("A", "HUB", 50, 60), _leg("HUB", "B", 50, 60))   # total 100, 120min
    pricey_fast = (_leg("A", "B", 3000, 60),)                          # total 3000, 60min

    ranked = rank_itineraries([cheap_slow, pricey_fast], cost_weight=1.0, time_weight=0.0)

    assert ranked[0].legs == cheap_slow
    assert ranked[0].total_fare == 100
    assert ranked[1].legs == pricey_fast


def test_rank_itineraries_puts_the_fastest_option_first_when_time_is_all_that_matters():
    cheap_slow = (_leg("A", "HUB", 50, 60), _leg("HUB", "B", 50, 60))
    pricey_fast = (_leg("A", "B", 3000, 60),)

    ranked = rank_itineraries([cheap_slow, pricey_fast], cost_weight=0.0, time_weight=1.0)

    # both take 120 total? no -- pricey_fast is 60min total vs cheap_slow's 120min total
    assert ranked[0].legs == pricey_fast
    assert ranked[0].total_duration_minutes == 60
    assert ranked[1].legs == cheap_slow


def test_rank_itineraries_balanced_weights_can_favor_a_middle_option_over_either_extreme():
    cheapest_slowest = (_leg("A", "B", 100, 400),)
    fastest_priciest = (_leg("A", "B", 4000, 75),)
    balanced = (_leg("A", "B", 900, 150),)

    ranked = rank_itineraries(
        [cheapest_slowest, fastest_priciest, balanced], cost_weight=0.5, time_weight=0.5,
    )

    assert ranked[0].legs == balanced


def test_rank_itineraries_returns_empty_list_for_no_candidates():
    assert rank_itineraries([]) == []


def test_itinerary_total_fare_and_duration_sum_across_all_legs():
    from trip_planner.planner import Itinerary

    itinerary = Itinerary(legs=(_leg("A", "HUB", 90, 12), _leg("HUB", "B", 899, 360)))

    assert itinerary.total_fare == 989
    assert itinerary.total_duration_minutes == 372
    assert itinerary.leg_count == 2
