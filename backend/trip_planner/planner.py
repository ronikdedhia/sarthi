"""BUILD_PLAN.md Phase 2's leg-graph + multi-objective itinerary search -- the actual
intellectual core of Sarthi (ARCHITECTURE.md: "a real graph/optimization problem, not a
for-loop"). Pure, DB-free graph logic over a small set of candidate legs -- deliberately
separate from the DB/HTTP-touching code in trip_planner/services.py so it's testable with
plain crafted inputs (see trip_planner/tests/test_planner.py), not Django fixtures or a
running mock_bpp server.

Design: mock_bpp's routes (catalog.py) connect a small set of NAMED PLACES rather than
arbitrary geography. Given a set of candidate LegOptions (one per real ONDC offer,
already carrying from_place/to_place/fare/duration/mode), build_graph turns them into an
undirected adjacency list (each transit service is usable in either direction), and
find_itinerary_paths enumerates every simple path from origin to destination up to a
leg cap via DFS -- the graph here is small (a handful of named places), so exhaustive
simple-path enumeration is the right tool, not an approximation or a heuristic search.
rank_itineraries then scores each candidate path by a weighted sum of normalized total
fare and total duration, so callers can trade cost off against speed (cost_weight=1.0 is
"cheapest first" even if far slower; time_weight=1.0 is "fastest first" even if far
pricier) rather than this module silently picking one fixed definition of "best"."""
import dataclasses
from collections import defaultdict


@dataclasses.dataclass(frozen=True)
class LegOption:
    """One candidate leg for the graph -- built from an ondc_adapter Offer, but the
    graph/search logic below only needs these fields, not Offer's ONDC-specific ones
    (bpp_id, item_id, raw, ...), which travel along via `offer` for later booking."""

    from_place: str
    to_place: str
    fare: float
    duration_minutes: int
    mode: str
    offer: object = None


@dataclasses.dataclass(frozen=True)
class Itinerary:
    """One ranked, ordered sequence of legs from origin to destination."""

    legs: tuple

    @property
    def total_fare(self):
        return sum(leg.fare for leg in self.legs)

    @property
    def total_duration_minutes(self):
        return sum(leg.duration_minutes for leg in self.legs)

    @property
    def leg_count(self):
        return len(self.legs)


def build_graph(leg_options):
    """Adjacency list keyed by place name -> list of LegOption usable FROM that place.
    Every leg is bidirectional (these are real scheduled/on-demand transit services, not
    one-way-only routes) -- both directions are added even though mock_bpp's catalog only
    lists each route once."""
    graph = defaultdict(list)
    for leg in leg_options:
        graph[leg.from_place].append(leg)
        graph[leg.to_place].append(dataclasses.replace(leg, from_place=leg.to_place, to_place=leg.from_place))
    return graph


def find_itinerary_paths(graph, origin, destination, max_legs=4):
    """Enumerates every simple path (no repeated place) from origin to destination, up
    to max_legs edges, via DFS. Returns a list of tuples-of-LegOption, one per path --
    empty if origin/destination aren't connected within max_legs hops (e.g. either place
    isn't a recognized node in the mock catalog's small demo graph at all)."""
    if origin == destination:
        return []

    paths = []

    def dfs(current, visited, path):
        if len(path) > max_legs:
            return
        if current == destination and path:
            paths.append(tuple(path))
            return
        for leg in graph.get(current, []):
            if leg.to_place in visited:
                continue
            visited.add(leg.to_place)
            path.append(leg)
            dfs(leg.to_place, visited, path)
            path.pop()
            visited.discard(leg.to_place)

    dfs(origin, {origin}, [])
    return paths


def _normalize(value, lo, hi):
    return 0.0 if hi == lo else (value - lo) / (hi - lo)


def rank_itineraries(paths, cost_weight=0.5, time_weight=0.5):
    """Multi-objective ranking: normalizes total fare and total duration across all
    candidate itineraries to [0, 1] each (min -> 0, max -> 1), then scores each by
    cost_weight * cost_score + time_weight * time_score -- lower score ranks first.
    cost_weight/time_weight need not sum to 1; only their ratio matters. Returns
    Itinerary objects sorted best-first; empty input returns an empty list rather than
    dividing by nothing."""
    itineraries = [Itinerary(legs=path) for path in paths]
    if not itineraries:
        return []

    fares = [it.total_fare for it in itineraries]
    durations = [it.total_duration_minutes for it in itineraries]
    min_fare, max_fare = min(fares), max(fares)
    min_duration, max_duration = min(durations), max(durations)

    def _score(it):
        cost_score = _normalize(it.total_fare, min_fare, max_fare)
        time_score = _normalize(it.total_duration_minutes, min_duration, max_duration)
        return cost_weight * cost_score + time_weight * time_score

    return sorted(itineraries, key=_score)
