"""Economy prior model configuration (issue #1151).

All tunable parameters for the running economy prior model are centralised
here.  Changing a value in this file (or constructing an EconomyPriorConfig
with non-default arguments) is the only code change required to alter the
model's behaviour — no magic numbers remain in the model source files.

Parameters
----------
lag_length_days : int
    Days from a training session to the kernel's peak weight.  Sessions at
    this exact lag contribute the maximum kernel weight.  Sessions newer or
    older contribute less.  Default: 42 days (6 weeks).

ramp_window_days : int
    Total window (in calendar days) over which past sessions contribute to
    the lagged ceiling bonus.  Sessions older than this many days contribute
    nothing.  Must be between 42 and 84 days (6–12 weeks inclusive); values
    outside this range raise ValueError immediately on instantiation.
    Default: 84 days (12 weeks).

speed_weights : dict
    Speed-dependence weights that control how running speed modulates each
    training-modality contribution:

      ``strength_speed_scale``      — km/h reference speed at which the speed
                                      factor doubles the baseline strength
                                      weight (speed_factor = 1 + speed / scale).
                                      Default: 20.0 km/h.

      ``strength_fitness_scale``    — Fitness reference value at which the
                                      fitness factor doubles the baseline
                                      strength weight.  Default: 100.0.

      ``plyo_speed_threshold``      — km/h above which the plyo weight begins
                                      to taper.  Below this speed the weight is
                                      close to its maximum; above it the weight
                                      falls toward zero.  Default: 12.0 km/h.

      ``plyo_below_taper_fraction`` — Fraction of the plyo weight lost linearly
                                      as speed rises from 0 to the threshold.
                                      Default: 0.1 (10% gentle reduction).

combination_bonus : float
    Multiplier applied to the total stimulus when both ``strength_load > 0``
    and ``plyo_contacts > 0`` in the same session.  A value of 1.1 grants a
    10% combined-modality synergy bonus.  1.0 means no bonus.
    Default: 1.1.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Weeks-to-days conversion and ramp-window bounds used in validation.
_WEEKS_TO_DAYS: int = 7
_RAMP_WINDOW_MIN_WEEKS: int = 6   # 42 days
_RAMP_WINDOW_MAX_WEEKS: int = 12  # 84 days


@dataclass
class EconomyPriorConfig:
    """Tunable parameters for the running economy prior model.

    All four economy prior parameters (lag length, ramp window,
    speed-dependence weights, and combination bonus) live here.
    Construct a custom instance to experiment; pass it to the model
    functions via their ``config`` keyword argument.
    """

    # Days from a session to the kernel's peak weight.  Default: 42 (6 weeks).
    lag_length_days: int = 42

    # Total window in days over which sessions contribute.  Valid: 6–12 weeks.
    # Default: 84 (12 weeks).
    ramp_window_days: int = 84

    # Speed-dependence weights (dict).  See module docstring for key definitions.
    speed_weights: dict = field(default_factory=lambda: {
        "strength_speed_scale": 20.0,
        "strength_fitness_scale": 100.0,
        "plyo_speed_threshold": 12.0,
        "plyo_below_taper_fraction": 0.1,
    })

    # Multiplier when both strength load and plyo contacts are present.
    # Default: 1.1 (10% combined-modality bonus).
    combination_bonus: float = 1.1

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        min_days = _RAMP_WINDOW_MIN_WEEKS * _WEEKS_TO_DAYS
        max_days = _RAMP_WINDOW_MAX_WEEKS * _WEEKS_TO_DAYS
        if not (min_days <= self.ramp_window_days <= max_days):
            raise ValueError(
                f"ramp_window_days must be between {min_days} and {max_days} days "
                f"({_RAMP_WINDOW_MIN_WEEKS}–{_RAMP_WINDOW_MAX_WEEKS} weeks); "
                f"got {self.ramp_window_days}"
            )


# Singleton default config — imported by model modules when no override is supplied.
DEFAULT_ECONOMY_CONFIG: EconomyPriorConfig = EconomyPriorConfig()
