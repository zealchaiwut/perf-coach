"""Pure what-if weight projection: no I/O, no DB, no side effects (issue #877).

This module contains a single public function, ``simulate_what_if``, which
projects a forward weight line and computes the date a user would reach their
goal given a starting trend value, a goal weight, and a weekly rate of change.

A separate *caller* module (``weight_what_if_caller.py``) is responsible for
fetching ``actual_trend`` from the database and passing it in here; this file
imports nothing from the data layer.
"""
from __future__ import annotations

import datetime
from typing import Any, Callable, Union


def simulate_what_if(
    actual_trend: Union[dict, Callable, None],
    goal_weight_kg: Union[float, None],
    assumed_rate_kg_per_week: Union[float, None],
    today: Union[datetime.date, None],
) -> dict:
    """Project a forward weight line and compute the goal-arrival date.

    Given the user's actual weight trend, a target goal weight, and a
    user-supplied weekly rate of change, this function steps forward in
    time—one week per step—subtracting the assumed rate from the running
    weight on each step until the running weight reaches or crosses the
    goal weight.  The result is a list of weekly ``{date, weight}`` points
    (the *projected line*) together with the date of first arrival and a
    debug snapshot of intermediate values.

    Parameters
    ----------
    actual_trend:
        Weight trend data from which the starting weight is read.
        Accepted forms:

        * **dict** mapping :class:`datetime.date` (or ISO strings) to
          ``float`` weights — the value at ``today`` is used.
        * **callable** ``(date) -> float`` — called with ``today`` to obtain
          the starting weight.

        Pass ``None`` to receive an empty-result error response.
    goal_weight_kg:
        The target weight in kilograms the user wants to reach.
        Pass ``None`` to receive an empty-result error response.
    assumed_rate_kg_per_week:
        The assumed weekly change in kilograms (negative = weight loss,
        positive = weight gain).  Pass ``0`` or ``None`` to receive an
        empty-result error response.
    today:
        The anchor date for the simulation.  The projected line starts here.
        Pass ``None`` to receive an empty-result error response.

    Returns
    -------
    dict
        On success::

            {
                "projected_line": [{"date": date, "weight": float}, ...],
                "arrival_date":   datetime.date,
                "debug":          {
                    "starting_weight": float,
                    "goal_weight_kg":  float,
                    "rate_per_week":   float,
                    "today":           date,
                    "steps":           int,
                },
            }

        On any validation failure (missing input, zero rate, wrong direction,
        goal already reached)::

            {
                "projected_line": [],
                "arrival_date":   None,
                "debug":          {},
                "reason":         "<human-readable explanation>",
            }

    How the math works (plain English)
    ------------------------------------
    1. The **starting weight** is looked up in ``actual_trend`` for ``today``.
    2. A loop runs one step at a time.  On each step, one calendar week
       (7 days) is added to the current date, and
       ``assumed_rate_kg_per_week`` is added to the running weight.
       Because ``assumed_rate_kg_per_week`` is negative for weight loss,
       *adding* a negative number decreases the running weight.
    3. The loop continues until the running weight reaches or crosses
       ``goal_weight_kg`` (i.e., for a loss scenario the weight drops to
       or below the goal; for a gain scenario it rises to or above it).
    4. The date of that final step is the **arrival date**.

    Worked examples
    ---------------
    **Example 1 — slow loss at −0.3 kg/week:**

        actual_trend = {date(2026, 6, 21): 90.0}
        goal_weight_kg = 80.0
        assumed_rate_kg_per_week = -0.3
        today = date(2026, 6, 21)

        Starting weight = 90.0 kg.
        Each step subtracts 0.3 kg.  10 kg ÷ 0.3 kg/week ≈ 33.3 weeks.

        → arrival_date ≈ date(2026, 6, 21) + 34 weeks ≈ date(2027, 2, 14)

    **Example 2 — faster loss at −0.4 kg/week:**

        actual_trend = {date(2026, 6, 21): 90.0}
        goal_weight_kg = 80.0
        assumed_rate_kg_per_week = -0.4
        today = date(2026, 6, 21)

        Starting weight = 90.0 kg.
        Each step subtracts 0.4 kg.  10 kg ÷ 0.4 kg/week = 25 weeks.

        → arrival_date ≈ date(2026, 6, 21) + 25 weeks ≈ date(2026, 12, 13)

        Because −0.4 kg/week is faster than −0.3 kg/week, the arrival
        date is earlier.
    """
    def _empty(reason: str) -> dict:
        return {
            "projected_line": [],
            "arrival_date": None,
            "debug": {},
            "reason": reason,
        }

    # ── validate inputs ───────────────────────────────────────────────────────
    if actual_trend is None:
        return _empty("actual_trend is required but was not provided")

    if today is None:
        return _empty("today is required but was not provided")

    if goal_weight_kg is None:
        return _empty("goal_weight_kg is required but was not provided")

    if assumed_rate_kg_per_week is None:
        return _empty("assumed_rate_kg_per_week is required but was not provided")

    # ── resolve starting weight from actual_trend ─────────────────────────────
    try:
        if callable(actual_trend):
            starting_weight = float(actual_trend(today))
        elif hasattr(actual_trend, "__getitem__"):
            # dict or dict-like: try exact date key first, then ISO string
            if today in actual_trend:
                starting_weight = float(actual_trend[today])
            elif str(today) in actual_trend:
                starting_weight = float(actual_trend[str(today)])
            else:
                return _empty(
                    f"actual_trend does not contain an entry for today ({today})"
                )
        else:
            return _empty(
                "actual_trend must be a dict mapping dates to weights or a callable"
            )
    except (KeyError, TypeError, ValueError) as exc:
        return _empty(f"could not read starting weight from actual_trend: {exc}")

    goal = float(goal_weight_kg)
    rate = float(assumed_rate_kg_per_week)

    # ── validate rate and direction ───────────────────────────────────────────
    if rate == 0:
        return _empty(
            "assumed_rate_kg_per_week is 0 — weight would never change and "
            "the goal would never be reached"
        )

    is_loss_goal = goal < starting_weight
    is_loss_rate = rate < 0

    if is_loss_goal and not is_loss_rate:
        return _empty(
            f"rate {rate:+.4g} kg/week is in the wrong direction: goal "
            f"({goal} kg) is below starting weight ({starting_weight} kg) "
            "but the rate is positive (gaining)"
        )

    if not is_loss_goal and is_loss_rate:
        return _empty(
            f"rate {rate:+.4g} kg/week is in the wrong direction: goal "
            f"({goal} kg) is above starting weight ({starting_weight} kg) "
            "but the rate is negative (losing)"
        )

    if is_loss_goal and starting_weight <= goal:
        return _empty(
            f"starting weight ({starting_weight} kg) is already at or below "
            f"goal ({goal} kg)"
        )

    if not is_loss_goal and starting_weight >= goal:
        return _empty(
            f"starting weight ({starting_weight} kg) is already at or above "
            f"goal ({goal} kg)"
        )

    # ── project the weekly line ───────────────────────────────────────────────
    projected_line: list[dict] = []
    current_date = today
    current_weight = starting_weight

    while True:
        projected_line.append({"date": current_date, "weight": round(current_weight, 6)})

        # Check if goal reached or crossed
        if is_loss_goal and current_weight <= goal:
            arrival_date = current_date
            break
        if not is_loss_goal and current_weight >= goal:
            arrival_date = current_date
            break

        # Step forward one week
        current_date = current_date + datetime.timedelta(weeks=1)
        current_weight = current_weight + rate

    debug = {
        "starting_weight": starting_weight,
        "goal_weight_kg": goal,
        "rate_per_week": rate,
        "today": today,
        "steps": len(projected_line) - 1,
    }

    return {
        "projected_line": projected_line,
        "arrival_date": arrival_date,
        "debug": debug,
    }
