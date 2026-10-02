"""Union-find clustering over flagged pairs: connected components of the
similarity graph expose 'one source circulated to N students' patterns."""


class DSU:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def clusters_from_pairs(pairs, min_score):
    """pairs: list of PairResult. Returns [ (size, [rolls...]), ... ] sorted
    by size desc — components joined by edges with score >= min_score."""
    dsu = DSU()
    for p in pairs:
        if p.blended >= min_score:
            dsu.union(p.roll_a, p.roll_b)
    groups = {}
    for roll in list(dsu.parent):
        groups.setdefault(dsu.find(roll), []).append(roll)
    out = [sorted(v) for v in groups.values() if len(v) > 1]
    out.sort(key=len, reverse=True)
    return out
