"""Lab 04 starter — graph edge list from the lab manual.
CopCat subtracts fingerprints from this file before scoring."""

# Undirected graph edge list (index = node, value = neighbours)
# Nodes: A(0), B(1), C(2), D(3), E(4), F(5)
edge = [
    ["B", "C"],         # neighbours of A
    ["A", "D", "E"],    # neighbours of B
    ["A", "F"],         # neighbours of C
    ["B"],              # neighbours of D
    ["B"],              # neighbours of E
    ["C"],              # neighbours of F
]

# 4-puzzle goal state (flat tuple: index 0=top-left, 3=bottom-right)
GOAL_STATE = (1, 2, 3, 0)
