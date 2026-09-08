import numpy as np

from aegisquant.research.validation.paired_bootstrap import holm_adjust, paired_block_bootstrap


def test_paired_blocks_preserve_identical_paths_and_known_constant_difference() -> None:
    path = np.sin(np.arange(240)) / 1000
    values = np.column_stack((path, path, path + 0.01))
    result = paired_block_bootstrap(values, repetitions=10000, block_bars=6, seed=7)
    same = result.difference(1, 0)
    assert same["ci95_lower"] == same["ci95_upper"] == 0
    assert result.difference(2, 0)["ci95_lower"] > 0
    assert result.repetitions == 10000
    assert holm_adjust({"a": 0.01, "b": 0.03}) == {"a": 0.02, "b": 0.03}
