"""nikke_opt.similarity — 쌍 자카드 · 바꿀 니케 수."""

import unittest

from nikke_opt import similarity as S

GRID = [[f"{r}{c}" for c in range(5)] for r in "ABCDE"]


def swapped(a, i, b, j, plan=GRID):
    x = [list(d) for d in plan]
    x[a][i], x[b][j] = x[b][j], x[a][i]
    return x


class TestSimilarity(unittest.TestCase):
    def test_identical_ignores_order(self):
        shuffled = [list(reversed(d)) for d in reversed(GRID)]
        self.assertEqual(S.compare(GRID, shuffled), {"pair_jaccard": 1.0, "pair_shared": 50, "moves": 0, "shared_nikkes": 25})

    def test_one_swap(self):
        c = S.compare(GRID, swapped(0, 0, 1, 0))
        self.assertEqual((c["pair_shared"], c["moves"], c["shared_nikkes"]), (42, 2, 25))
        self.assertAlmostEqual(c["pair_jaccard"], 42 / 58)

    def test_same_members_regrouped(self):
        regrouped = [[GRID[r][(c + r) % 5] for r in range(5)] for c in range(5)]
        c = S.compare(GRID, regrouped)
        self.assertEqual((c["pair_jaccard"], c["moves"], c["shared_nikkes"]), (0.0, 20, 25))

    def test_disjoint_and_different_members(self):
        other = [[f"Z{r}{c}" for c in range(5)] for r in range(5)]
        self.assertEqual(S.compare(GRID, other)["moves"], 25)
        one_out = [list(d) for d in GRID]
        one_out[0][0] = "Z"
        c = S.compare(GRID, one_out)
        self.assertEqual((c["pair_shared"], c["moves"], c["shared_nikkes"]), (46, 1, 24))
        self.assertAlmostEqual(c["pair_jaccard"], 46 / 54)

    def test_symmetric_and_bounded(self):
        b = swapped(2, 1, 4, 3, swapped(0, 0, 1, 0))
        self.assertEqual(S.compare(GRID, b), S.compare(b, GRID))
        self.assertTrue(0.0 <= S.pair_jaccard(GRID, b) <= 1.0)

    def test_matching_is_optimal_not_greedy(self):
        a = [["1", "2", "3", "4", "5"], ["6", "7"]]
        b = [["1", "2", "3", "6", "7"], ["4", "5"]]
        self.assertEqual(S.matched_members(a, b), 4)    # 탐욕(가장 큰 3부터)이면 3 + 0, 최적은 2 + 2
        self.assertEqual(S.matched_members([["a", "b"]], [["a"], ["b"]]), 1)

    def test_empty(self):
        self.assertEqual(S.pair_jaccard([], []), 1.0)
        self.assertEqual(S.matched_members([], [["a"]]), 0)


if __name__ == "__main__":
    unittest.main()
