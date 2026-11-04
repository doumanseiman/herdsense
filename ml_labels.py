"""Shared model labels and mappings between rules, training, and dashboard states."""
from __future__ import annotations

from rules import LOST, SEPARATED, TOGETHER, WAITING

SAFE = "AMAN"
MOVING_AWAY = "MULAI MENJAUH"
STRAGGLER = "TERTINGGAL"
APART = "TERPISAH"
LOST_SIGNAL = LOST

MODEL_LABELS = (SAFE, MOVING_AWAY, STRAGGLER, APART)
RULE_TO_LABEL = {
    TOGETHER: SAFE,
    WAITING: STRAGGLER,
    SEPARATED: APART,
}
