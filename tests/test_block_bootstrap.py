import os
import sys
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import bootstrap_mean_diff_ci

# Unit test for block bootstrap interval behavior.

x = np.arange(20, dtype=float)
y = np.arange(20, dtype=float) + 1.0

ci_lower, ci_upper, point = bootstrap_mean_diff_ci(
    x,
    y,
    confidence=0.95,
    n_resamples=200,
    random_seed=1,
    mode='block',
    block_size=4,
)

assert ci_lower <= point <= ci_upper
print('Block bootstrap test passed.')
