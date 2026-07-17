from sqlalchemy import BigInteger, Boolean, Column, Index, Integer, LargeBinary, String, Numeric, Float, Date, DateTime, Time, ForeignKey, UniqueConstraint, CheckConstraint, text, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base, deferred, relationship, validates

Base = declarative_base()


def compute_goal_pace(goal_time_seconds, distance_km):
    """Derive goal pace in seconds per kilometre from race time and distance.

    Returns a 2-tuple ``(pace, reason)`` where *pace* is the rounded integer
    pace (seconds per km) and *reason* is ``None`` on success, or a non-empty
    human-readable string explaining why the pace cannot be computed.

    Invalid when either input is ``None``, zero, or negative — in those cases
    the function returns ``(None, reason)`` rather than raising.

    :param goal_time_seconds: Total goal race time in seconds, or ``None``.
    :param distance_km: Race distance in kilometres, or ``None``.
    :returns: ``(int, None)`` on success; ``(None, str)`` on invalid input.
    """
    if goal_time_seconds is None:
        return (None, "goal_time_seconds is required")
    if distance_km is None:
        return (None, "distance_km is required")
    if goal_time_seconds <= 0:
        return (None, "goal_time_seconds must be positive")
    if distance_km <= 0:
        return (None, "distance_km must be positive")
    return (round(goal_time_seconds / distance_km), None)


def derive_goal_pace(goal_time_seconds, distance_km):
    """Backwards-compatible shim — returns just the pace integer (or ``None``).

    Delegates to :func:`compute_goal_pace` and discards the reason string so
    that existing callers that expect a plain ``int | None`` continue to work.
    """
    pace, _ = compute_goal_pace(goal_time_seconds, distance_km)
    return pace


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name = Column(String(100), nullable=False, unique=True)
    email = Column(String(255), nullable=True)
    is_admin = Column(Boolean, nullable=False, server_default=text("false"))
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    password_hash = Column(Text, nullable=True)
    avatar = Column(LargeBinary, nullable=True)
    avatar_mime = Column(Text, nullable=True)
    height_cm = Column(Numeric(5, 1), nullable=True)


class WeightEntry(Base):
    __tablename__ = "weight_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    entry_date = Column(Date, nullable=False)
    entry_time = Column(Time, nullable=True)
    weight_kg = Column(Numeric(5, 2), nullable=False)
    notes = Column(Text, nullable=True)
    source = Column(String(20), nullable=False, server_default=text("'manual'"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint(
            "user_id", "entry_date", "entry_time",
            name="uq_weight_entries_user_date_time",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_weight_entries_user_entry_date", "user_id", "entry_date"),
        Index(
            "ix_weight_entries_user_date_null_time",
            "user_id",
            "entry_date",
            unique=True,
            postgresql_where=text("entry_time IS NULL"),
        ),
        CheckConstraint(
            "source IN ('manual', 'imported', 'backfill')",
            name="ck_weight_entries_source_values",
        ),
    )


class WeightTarget(Base):
    __tablename__ = "weight_targets"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    start_weight_kg = Column(Numeric(5, 2), nullable=False)
    start_date = Column(Date, nullable=False)
    target_weight_kg = Column(Numeric(5, 2), nullable=False)
    target_date = Column(Date, nullable=False)
    status = Column(String(20), nullable=False, server_default=text("'active'"))
    ended_at = Column(DateTime(timezone=True), nullable=True)
    end_weight_kg = Column(Numeric(5, 2), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'achieved', 'abandoned', 'replaced')",
            name="ck_weight_targets_status_values",
        ),
        Index("ix_weight_targets_user_status", "user_id", "status"),
        # Partial unique index — one active target per user; enforced at DB level
        Index(
            "uix_weight_targets_one_active_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )


_HABIT_TYPE_VALUES = ("binary", "count", "duration")
_SCHEDULE_TYPE_VALUES = ("daily", "weekly", "times_per_week")


class Habit(Base):
    __tablename__ = "habits"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(200), nullable=False)
    # v2 schema columns (issue #821)
    habit_type = Column(Text, nullable=False, server_default=text("'binary'"))
    target_value = Column(Numeric(12, 4), nullable=True)
    unit = Column(String(50), nullable=True)
    schedule_type = Column(Text, nullable=False, server_default=text("'daily'"))
    schedule_target = Column(Integer, nullable=True)
    active = Column(Boolean, nullable=False, server_default=text("true"))
    display_order = Column(Integer, nullable=False, server_default=text("0"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=True)
    # Legacy columns retained for backward-compat with existing code
    description = Column(Text, nullable=True)
    tracking_type = Column(String(50), nullable=False, server_default=text("'daily_checkmark'"))
    weekly_target = Column(Numeric(10, 2), nullable=True)
    auto_fill_source = Column(String(100), nullable=True)
    icon = Column(String(100), nullable=True)
    color = Column(String(20), nullable=True)
    sort_order = Column(Integer, nullable=False, server_default=text("0"))
    is_archived = Column(Boolean, nullable=False, server_default=text("false"))
    archived_at = Column(DateTime(timezone=True), nullable=True)
    # Focus-aware coaching fields (issue #925)
    minimum_version = Column(Text, nullable=True)
    anchor_event = Column(Text, nullable=True)
    # Three-focus-habit model (issue #924)
    is_focus = Column(Boolean, nullable=True)
    focus_since = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "habit_type IN ('binary', 'count', 'duration')",
            name="ck_habits_habit_type_values",
        ),
        CheckConstraint(
            "schedule_type IN ('daily', 'weekly', 'times_per_week')",
            name="ck_habits_schedule_type_values",
        ),
    )

    habit_logs = relationship(
        "HabitLog",
        back_populates="habit",
        cascade="all, delete-orphan",
        order_by="HabitLog.log_date",
    )

    @validates("habit_type")
    def _validate_habit_type(self, key, value):
        if value not in _HABIT_TYPE_VALUES:
            raise ValueError(
                f"habit_type must be one of {_HABIT_TYPE_VALUES}, got {value!r}"
            )
        return value

    @validates("schedule_type")
    def _validate_schedule_type(self, key, value):
        if value not in _SCHEDULE_TYPE_VALUES:
            raise ValueError(
                f"schedule_type must be one of {_SCHEDULE_TYPE_VALUES}, got {value!r}"
            )
        return value

    def effective_schedule_target(self):
        """Return ``(schedule_target, None)`` when set.

        Returns ``(None, reason)`` when ``schedule_target`` is absent so callers
        never need to guard against an unhandled exception.
        """
        if self.schedule_target is None:
            return (None, "schedule_target is not set for this habit")
        return (self.schedule_target, None)


class HabitLog(Base):
    """Habit log entries. For daily_checkmark habits, one row per day checked (value=1). For weekly_count/minutes/quantity habits, one row per logged event with the contributed value. Week aggregation done at read time by summing values where log_week_start matches."""

    __tablename__ = "habit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    habit_id = Column(UUID(as_uuid=True), ForeignKey("habits.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    log_date = Column(Date, nullable=False)
    value = Column(Numeric(10, 4), nullable=False, server_default=text("1"))
    # v2 column (issue #821)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=True)
    # Legacy columns retained for backward-compat with existing code
    log_week_start = Column(Date, nullable=False)
    notes = Column(Text, nullable=True)
    source = Column(String(50), nullable=False, server_default=text("'manual'"))

    __table_args__ = (
        UniqueConstraint("habit_id", "log_date", name="uq_habit_logs_habit_log_date"),
        Index("ix_habit_logs_habit_id_log_week_start", "habit_id", "log_week_start"),
    )

    habit = relationship("Habit", back_populates="habit_logs")


class Workout(Base):
    __tablename__ = "workouts"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    workout_date = Column(Date, nullable=False)
    name = Column(String(200), nullable=False)
    workout_type = Column(String(50), nullable=False)
    # Optional run subtype (interval | longrun | easy | tempo | NULL). Runs keep
    # workout_type='run' so they stay in the full run pipeline; this labels the
    # kind of run for the Performance Speed feed / "what's moving".
    run_subtype = Column(String(20), nullable=True)
    remarks = Column(Text, nullable=True)
    tss = Column(Float, nullable=True)
    tss_source = Column(String(20), nullable=True)
    tss_method = Column(String(20), nullable=True)
    source = Column(String(20), nullable=True)
    strava_activity_url = Column(Text, nullable=True)
    distance_km = Column(Numeric(8, 3), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    avg_hr = Column(Integer, nullable=True)
    max_hr = Column(Integer, nullable=True)
    elevation_m = Column(Integer, nullable=True)
    start_time = Column(DateTime(timezone=True), nullable=True)
    strava_activity_pk = Column(UUID(as_uuid=True), ForeignKey("strava_activities.id", ondelete="SET NULL"), nullable=True)
    stryd_activity_pk = Column(UUID(as_uuid=True), ForeignKey("stryd_activities.id", ondelete="SET NULL"), nullable=True)
    manual_overrides = Column(JSONB, nullable=True)
    zone2_minutes = Column(Integer, nullable=True)
    # Workout-level Stryd power/cadence/stride aggregates (nullable; manual runs → null).
    avg_power = Column(Integer, nullable=True)
    max_power = Column(Integer, nullable=True)
    np = Column(Integer, nullable=True)
    avg_cadence_spm = Column(Integer, nullable=True)
    avg_stride_m = Column(Numeric(4, 2), nullable=True)
    # Computed speed signal (issue #1048): best short-effort ratio vs threshold.
    speed_signal = Column(Float, nullable=True)
    speed_signal_basis = Column(String(20), nullable=True)
    speed_signal_window_seconds = Column(Integer, nullable=True)
    speed_signal_source = Column(Text, nullable=True)
    # Environmental conditions at time of run (issue #1168).
    temperature_c = Column(Float, nullable=True)
    humidity_pct = Column(Float, nullable=True)
    # Computed endurance signal (issue #1049): aerobic durability metric; runs ≥ 40 min only.
    endurance_signal = Column(Float, nullable=True)
    decoupling_percent = Column(Float, nullable=True)
    efficiency_first_half = Column(Float, nullable=True)
    efficiency_second_half = Column(Float, nullable=True)
    endurance_signal_source = Column(String(20), nullable=True)
    # Flat-equivalent pace for treadmill activities (issue #1219): computed from
    # normalize_treadmill_signal via the Minetti NGP formula. None for outdoor runs.
    flat_equivalent_pace = Column(Float, nullable=True)
    # Self-reported effort feeling (issue #1241): 'hard' | 'ok' | 'easy' | NULL.
    # One shared column tagged from either the Plan tab (matched workout) or the
    # Log tab. Does not affect scores.
    feeling = Column(String(10), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    # Column already exists in the DB; map it so edits can stamp it and the
    # summary/performance cache signature can include MAX(updated_at).
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=text("now()"))

    __table_args__ = (
        CheckConstraint("tss IS NULL OR tss >= 0", name="ck_workouts_tss_non_negative"),
        CheckConstraint("tss_source IS NULL OR tss_source IN ('manual', 'calculated', 'stryd', 'power', 'pace', 'hr', 'duration_only')", name="ck_workouts_tss_source_values"),
        CheckConstraint("source IS NULL OR source IN ('manual', 'strava', 'stryd', 'strava,stryd', 'stryd,strava', 'both')", name="ck_workouts_source_values"),
        CheckConstraint("distance_km IS NULL OR distance_km >= 0", name="ck_workouts_distance_non_negative"),
        CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0", name="ck_workouts_duration_non_negative"),
        CheckConstraint("avg_hr IS NULL OR (avg_hr >= 20 AND avg_hr <= 250)", name="ck_workouts_avg_hr_range"),
        CheckConstraint("max_hr IS NULL OR (max_hr >= 20 AND max_hr <= 250)", name="ck_workouts_max_hr_range"),
        CheckConstraint("feeling IS NULL OR feeling IN ('hard', 'ok', 'easy')", name="ck_workouts_feeling_values"),
        # Matches alembic/versions/c3d4e5f6a7b8_create_workouts_table.py's raw-SQL
        # index (already in the DB) — declared here so autogenerate stays quiet.
        Index("ix_workouts_user_id_workout_date", "user_id", workout_date.desc()),
    )

    exercises = relationship(
        "WorkoutExercise",
        back_populates="workout",
        cascade="all, delete-orphan",
        order_by="WorkoutExercise.display_order",
    )

    splits = relationship(
        "WorkoutSplit",
        back_populates="workout",
        cascade="all, delete-orphan",
        order_by="WorkoutSplit.split_index",
    )

    strava_activity = relationship(
        "StravaActivity",
        foreign_keys="[Workout.strava_activity_pk]",
        lazy="select",
    )

    stryd_activity = relationship(
        "StrydActivity",
        foreign_keys="[Workout.stryd_activity_pk]",
        lazy="select",
    )


class WorkoutExercise(Base):
    __tablename__ = "workout_exercises"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    workout_id = Column(UUID(as_uuid=True), ForeignKey("workouts.id", ondelete="CASCADE"), nullable=False)
    display_order = Column(Integer, server_default=text("0"), nullable=False)
    # Training-block grouping (Warm-up / Heavy compound / Superset 1 / ...) —
    # same vocabulary as PlannedSession.structure.exercises[].block. Nullable:
    # old rows and ungrouped logs render flat. NOTE: restored after the
    # sprint-104 merge (15db9bb1) dropped this hunk while the DB column
    # (migration 1d5caaeaaa26) and every writer in main.py survived.
    block = Column(String(80), nullable=True)
    name = Column(String(200), nullable=False)
    sets = Column(Integer, nullable=True)
    reps = Column(Integer, nullable=True)
    weight_kg = Column(Numeric(6, 2), nullable=True)
    duration = Column(String(50), nullable=True)
    rpe = Column(Integer, nullable=True)
    distance_km = Column(Numeric(8, 3), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    avg_hr = Column(Integer, nullable=True)
    sets_json = Column(Text, nullable=True)  # per-set detail for strength builder
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        CheckConstraint("sets IS NULL OR sets > 0", name="ck_workout_exercises_sets_positive"),
        CheckConstraint("rpe IS NULL OR (rpe >= 1 AND rpe <= 10)", name="ck_workout_exercises_rpe_range"),
        CheckConstraint("distance_km IS NULL OR distance_km >= 0", name="ck_workout_exercises_distance_non_negative"),
        CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0", name="ck_workout_exercises_duration_non_negative"),
        CheckConstraint("avg_hr IS NULL OR (avg_hr >= 20 AND avg_hr <= 250)", name="ck_workout_exercises_avg_hr_range"),
    )

    workout = relationship("Workout", back_populates="exercises")


class WorkoutSplit(Base):
    __tablename__ = "workout_splits"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    workout_id = Column(UUID(as_uuid=True), ForeignKey("workouts.id", ondelete="CASCADE"), nullable=False)
    split_index = Column(Integer, nullable=False)
    distance_km = Column(Numeric(6, 3), nullable=False)
    duration_seconds = Column(Integer, nullable=False)
    avg_hr = Column(Integer, nullable=True)
    # Per-km Stryd metrics (nullable; manual/Strava-only splits → null).
    avg_power = Column(Integer, nullable=True)
    cadence_spm = Column(Integer, nullable=True)
    stride_length_m = Column(Numeric(4, 2), nullable=True)
    lap_type = Column(String(10), nullable=False, server_default=text("'auto'"))
    intensity_band = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("workout_id", "split_index", name="uq_workout_splits_workout_split_index"),
        CheckConstraint("lap_type IN ('auto', 'manual')", name="ck_workout_splits_lap_type_values"),
        CheckConstraint(
            "intensity_band IS NULL OR intensity_band IN ('easy', 'steady', 'tempo', 'threshold', 'hard')",
            name="ck_workout_splits_intensity_band_values",
        ),
    )

    workout = relationship("Workout", back_populates="splits")


class DailyMetric(Base):
    __tablename__ = "daily_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    metric_date = Column(Date, nullable=False)
    resting_hr = Column(Integer, nullable=True)
    hrv = Column(Integer, nullable=True)
    sleep_hours = Column(Numeric(3, 1), nullable=True)
    sleep_quality = Column(Integer, nullable=True)
    energy = Column(Integer, nullable=True)
    mood = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    kcal_intake = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("user_id", "metric_date", name="uq_daily_metrics_user_date"),
        CheckConstraint(
            "resting_hr IS NULL OR (resting_hr >= 20 AND resting_hr <= 200)",
            name="ck_daily_metrics_resting_hr",
        ),
        CheckConstraint(
            "hrv IS NULL OR (hrv >= 0 AND hrv <= 300)",
            name="ck_daily_metrics_hrv",
        ),
        CheckConstraint(
            "sleep_hours IS NULL OR (sleep_hours >= 0 AND sleep_hours <= 24)",
            name="ck_daily_metrics_sleep_hours",
        ),
        CheckConstraint(
            "sleep_quality IS NULL OR (sleep_quality >= 1 AND sleep_quality <= 5)",
            name="ck_daily_metrics_sleep_quality",
        ),
        CheckConstraint(
            "energy IS NULL OR (energy >= 1 AND energy <= 5)",
            name="ck_daily_metrics_energy",
        ),
        CheckConstraint(
            "mood IS NULL OR (mood >= 1 AND mood <= 5)",
            name="ck_daily_metrics_mood",
        ),
        CheckConstraint(
            "kcal_intake IS NULL OR kcal_intake > 0",
            name="ck_daily_metrics_kcal_intake",
        ),
    )


class FuelSettings(Base):
    """One row per user — the calorie-budget model's inputs (see
    docs/calculations/fuel.md and backend/services/fuel.py). Maintenance is
    an ESTIMATE until the calibrate flow runs (`maintenance_source`); never
    presented as authoritative — see fuel.md §0."""
    __tablename__ = "fuel_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    weight_kg = Column(Numeric(5, 2), nullable=False)
    lean_mass_kg = Column(Numeric(5, 2), nullable=True)  # fallback: weight_kg * 0.76
    base_kcal = Column(Integer, nullable=False)
    maintenance_source = Column(Text, nullable=False, server_default=text("'estimated'"))
    deficit_kcal = Column(Integer, nullable=False, server_default=text("300"))
    protein_g_per_kg = Column(Numeric(4, 2), nullable=False, server_default=text("2.0"))
    fat_g = Column(Integer, nullable=False, server_default=text("70"))
    ea_floor = Column(Numeric(5, 2), nullable=False, server_default=text("30.0"))
    run_kcal_per_kg_per_km = Column(Numeric(4, 2), nullable=False, server_default=text("1.0"))
    auto_periodize = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        CheckConstraint("maintenance_source IN ('estimated', 'measured')", name="ck_fuel_settings_maintenance_source"),
        CheckConstraint("deficit_kcal >= 0 AND deficit_kcal <= 750", name="ck_fuel_settings_deficit_kcal"),
        CheckConstraint("protein_g_per_kg >= 0.25 AND protein_g_per_kg <= 2.5", name="ck_fuel_settings_protein_g_per_kg"),
        CheckConstraint("fat_g > 0", name="ck_fuel_settings_fat_g"),
        CheckConstraint("ea_floor > 0", name="ck_fuel_settings_ea_floor"),
        CheckConstraint("run_kcal_per_kg_per_km > 0", name="ck_fuel_settings_run_kcal_per_kg_per_km"),
    )


class FuelEntry(Base):
    """One row per user per day (upsert, not append) — the day's logged food
    against the five tracked rows + a catch-all `other_*` bucket. See
    docs/calculations/fuel.md."""
    __tablename__ = "fuel_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    entry_date = Column(Date, nullable=False)
    meat_g = Column(Integer, nullable=False, server_default=text("0"))
    rice_g = Column(Integer, nullable=False, server_default=text("0"))
    eggs = Column(Integer, nullable=False, server_default=text("0"))
    fruit_g = Column(Integer, nullable=False, server_default=text("0"))
    oil_tsp = Column(Numeric(4, 1), nullable=False, server_default=text("0"))
    other_kcal = Column(Integer, nullable=False, server_default=text("0"))
    other_protein_g = Column(Numeric(6, 1), nullable=False, server_default=text("0"))
    other_carbs_g = Column(Numeric(6, 1), nullable=False, server_default=text("0"))
    other_fat_g = Column(Numeric(6, 1), nullable=False, server_default=text("0"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("user_id", "entry_date", name="uq_fuel_entries_user_date"),
        Index("ix_fuel_entries_user_date", "user_id", entry_date.desc()),
        CheckConstraint("meat_g >= 0", name="ck_fuel_entries_meat_g"),
        CheckConstraint("rice_g >= 0", name="ck_fuel_entries_rice_g"),
        CheckConstraint("eggs >= 0", name="ck_fuel_entries_eggs"),
        CheckConstraint("fruit_g >= 0", name="ck_fuel_entries_fruit_g"),
        CheckConstraint("oil_tsp >= 0", name="ck_fuel_entries_oil_tsp"),
        CheckConstraint("other_kcal >= 0", name="ck_fuel_entries_other_kcal"),
        CheckConstraint("other_protein_g >= 0", name="ck_fuel_entries_other_protein_g"),
        CheckConstraint("other_carbs_g >= 0", name="ck_fuel_entries_other_carbs_g"),
        CheckConstraint("other_fat_g >= 0", name="ck_fuel_entries_other_fat_g"),
    )


class PersonalRecord(Base):
    __tablename__ = "personal_records"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    track_key = Column(String(100), nullable=False)
    track_name = Column(String(200), nullable=False)
    track_type = Column(String(10), nullable=False)
    value_numeric = Column(Numeric(12, 4), nullable=False)
    achieved_on = Column(Date, nullable=False)
    source = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        CheckConstraint("track_type IN ('time', 'weight')", name="ck_personal_records_track_type"),
        CheckConstraint("value_numeric > 0", name="ck_personal_records_value_positive"),
    )


class StrengthPersonalRecord(Base):
    """Current best per (user, exercise_key, rep_band_label).

    When a new PR is set the old weight and its date are preserved in
    previous_weight_kg / previous_achieved_on so clients can show the delta.
    A row is created on first-ever ingest for an exercise; previous_weight_kg
    is NULL for that first record.
    """

    __tablename__ = "strength_personal_records"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    exercise_key = Column(String(200), nullable=False)
    exercise_name = Column(String(200), nullable=False)
    rep_band_label = Column(String(20), nullable=False)
    rep_band_min = Column(Integer, nullable=False)
    rep_band_max = Column(Integer, nullable=False)
    weight_kg = Column(Numeric(6, 2), nullable=False)
    reps = Column(Integer, nullable=False)
    previous_weight_kg = Column(Numeric(6, 2), nullable=True)
    previous_achieved_on = Column(Date, nullable=True)
    achieved_on = Column(Date, nullable=False)
    workout_id = Column(UUID(as_uuid=True), ForeignKey("workouts.id", ondelete="SET NULL"), nullable=True)
    exercise_id = Column(UUID(as_uuid=True), ForeignKey("workout_exercises.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("user_id", "exercise_key", "rep_band_label", name="uq_strength_pr_user_exercise_band"),
        CheckConstraint("weight_kg > 0", name="ck_strength_pr_weight_positive"),
        CheckConstraint("reps >= 1", name="ck_strength_pr_reps_positive"),
    )


class StrengthRecordAchievement(Base):
    """One row per PR-beating event, written at workout-ingest time.

    Retains enough context to populate the achievements feed and annotate the
    workout-full response without re-deriving history on every read.
    """

    __tablename__ = "strength_record_achievements"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    strength_record_id = Column(UUID(as_uuid=True), ForeignKey("strength_personal_records.id", ondelete="CASCADE"), nullable=False)
    exercise_key = Column(String(200), nullable=False)
    exercise_name = Column(String(200), nullable=False)
    rep_band_label = Column(String(20), nullable=False)
    new_weight_kg = Column(Numeric(6, 2), nullable=False)
    previous_weight_kg = Column(Numeric(6, 2), nullable=True)
    previous_achieved_on = Column(Date, nullable=True)
    achieved_on = Column(Date, nullable=False)
    workout_id = Column(UUID(as_uuid=True), ForeignKey("workouts.id", ondelete="SET NULL"), nullable=True)
    exercise_id = Column(UUID(as_uuid=True), ForeignKey("workout_exercises.id", ondelete="SET NULL"), nullable=True)
    set_index = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class StravaToken(Base):
    __tablename__ = "strava_tokens"

    # This sprint uses the DEFAULT user from users table for OAuth flows; user_id column exists for multi-user readiness later.
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    athlete_id = Column(BigInteger, nullable=False)
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    scope = Column(String(255), nullable=True)
    athlete_data = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))


class GoogleOAuthCredentials(Base):
    __tablename__ = "google_oauth_credentials"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    google_sub = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False)
    email_verified = Column(Boolean, nullable=False, server_default=text("false"))
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    id_token_payload = Column(JSONB, nullable=True)
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))


class DriveSleepConnection(Base):
    __tablename__ = "drive_sleep_connections"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    refresh_token_encrypted = Column(Text, nullable=True)
    folder_id = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, server_default=text("'not_connected'"))
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))


class StrydCredentials(Base):
    __tablename__ = "stryd_credentials"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    stryd_email = Column(String(255), nullable=False)
    stryd_password_encrypted = Column(Text, nullable=False)
    session_token = Column(Text, nullable=True)
    session_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    # Stryd athlete id is a UUID string (not numeric like Strava's).
    athlete_id = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))


class StravaActivity(Base):
    __tablename__ = "strava_activities"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    strava_activity_id = Column(BigInteger, nullable=False, unique=True, index=True)
    start_time = Column(DateTime(timezone=True), nullable=False, index=True)
    activity_type = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    distance_km = Column(Numeric(10, 3), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    avg_hr = Column(Integer, nullable=True)
    max_hr = Column(Integer, nullable=True)
    elevation_m = Column(Integer, nullable=True)
    avg_power_w = Column(Integer, nullable=True)
    max_power_w = Column(Integer, nullable=True)
    avg_cadence = Column(Numeric(6, 2), nullable=True)
    suffer_score = Column(Integer, nullable=True)
    device_name = Column(String(255), nullable=True)
    external_id = Column(String(255), nullable=True)
    is_stryd_synced = Column(Boolean, server_default=text("false"), nullable=False)
    raw_payload = deferred(Column(JSONB, nullable=False))
    # Full-capture blobs — everything Strava exposes per activity (decide what to
    # surface later). detail_payload = /activities/{id}; streams_payload = its /streams.
    detail_payload = deferred(Column(JSONB, nullable=True))
    streams_payload = deferred(Column(JSONB, nullable=True))
    synced_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)

    __table_args__ = (
        Index("ix_strava_activities_user_start_time", "user_id", "start_time"),
    )


class DailyReadiness(Base):
    __tablename__ = "daily_readiness"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    score = Column(Numeric(5, 2), nullable=False)
    components = Column(JSONB, nullable=False)
    computed_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    daily_metric_id = Column(
        UUID(as_uuid=True),
        ForeignKey("daily_metrics.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_daily_readiness_user_date"),
        CheckConstraint("score >= 0 AND score <= 100", name="ck_daily_readiness_score_range"),
        # Matches the raw-SQL index already in the DB (created by
        # 59a1b2c3d4e5_create_daily_readiness_table.py and its duplicate-head
        # counterpart) — declared here so autogenerate stays quiet. Queried
        # per-day per-user throughout readiness/training-load code.
        Index("ix_daily_readiness_user_date", "user_id", date.desc()),
    )


class StrydActivity(Base):
    __tablename__ = "stryd_activities"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    stryd_activity_id = Column(String(255), nullable=False, unique=True, index=True)
    start_time = Column(DateTime(timezone=True), nullable=False, index=True)
    name = Column(String(255), nullable=True)
    distance_km = Column(Numeric(10, 3), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    avg_power_w = Column(Integer, nullable=True)
    avg_hr = Column(Integer, nullable=True)
    tss = Column(Integer, nullable=True)
    form_metrics = deferred(Column(JSONB, nullable=True))
    power_zones = Column(JSONB, nullable=True)
    splits = deferred(Column(JSONB, nullable=True))
    streams_payload = deferred(Column(JSONB, nullable=True))
    raw_payload = deferred(Column(JSONB, nullable=False))
    # Computed at sync time by compute_manual_laps; avoids materialising streams_payload
    # on the detail request path (issue #1295).
    manual_laps = deferred(Column(JSONB, nullable=True))
    synced_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    # Treadmill incline extracted from the Stryd raw payload (average_incline field).
    # Present only for treadmill activities; None for outdoor runs.
    grade_percent = Column(Float, nullable=True)

    __table_args__ = (
        Index("ix_stryd_activities_user_start_time", "user_id", "start_time"),
    )


class RemovedActivity(Base):
    """Tombstone for a synced activity the user removed from their log.

    Keyed by the external activity id so reconcile skips it on future syncs and
    does not recreate the workout. Holds a name/date snapshot for the Removed
    list; deleting the row (restore) lets the next reconcile rebuild the workout.
    """

    __tablename__ = "removed_activities"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source = Column(String(10), nullable=False)  # 'strava' | 'stryd'
    external_id = Column(String(255), nullable=False)
    workout_name = Column(String(255), nullable=True)
    workout_date = Column(Date, nullable=True)
    removed_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "source", "external_id",
            name="uq_removed_activities_user_source_external",
        ),
        Index("ix_removed_activities_user", "user_id"),
    )


class WorkoutFeel(Base):
    __tablename__ = "workout_feel"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    feel_date = Column(Date, nullable=False)
    workout_id = Column(UUID(as_uuid=True), ForeignKey("workouts.id", ondelete="SET NULL"), nullable=True)
    rpe_1_to_10 = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        Index("ix_workout_feel_user_feel_date", "user_id", "feel_date"),
        CheckConstraint("rpe_1_to_10 >= 1 AND rpe_1_to_10 <= 10", name="ck_workout_feel_rpe_range"),
    )


class SleepImport(Base):
    __tablename__ = "sleep_imports"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source = Column(String(30), nullable=False)
    source_identifier = Column(String(255), nullable=True)
    import_date = Column(Date, nullable=False)
    raw_data = Column(JSONB, nullable=False)
    parsed_data = Column(JSONB, nullable=True)
    import_status = Column(String(20), nullable=False, server_default=text("'pending'"))
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        CheckConstraint(
            "source IN ('samsung_health', 'google_fit', 'manual_json', 'ocr_screenshot')",
            name="ck_sleep_imports_source_values",
        ),
        CheckConstraint(
            "import_status IN ('pending', 'parsed', 'merged', 'rejected', 'failed')",
            name="ck_sleep_imports_import_status_values",
        ),
        UniqueConstraint("user_id", "source", "source_identifier", name="uq_sleep_imports_user_source_identifier"),
        Index("ix_sleep_imports_user_import_date", "user_id", "import_date"),
    )


class AppConfig(Base):
    __tablename__ = "app_config"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))


class WorkoutTemplate(Base):
    __tablename__ = "workout_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(200), nullable=False)
    exercises = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        Index("ix_workout_templates_user_id", "user_id"),
    )


class UserPreferences(Base):
    __tablename__ = "user_preferences"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_user_preferences_user_id"),
        nullable=False,
        unique=True,
    )
    ftp_w = Column(Integer, nullable=True)
    ftp_w_source = Column(String(30), nullable=True)
    ftp_w_updated_at = Column(DateTime(timezone=True), nullable=True)
    threshold_hr = Column(Integer, nullable=True)
    threshold_hr_source = Column(String(30), nullable=True)
    threshold_hr_updated_at = Column(DateTime(timezone=True), nullable=True)
    threshold_pace_seconds_per_km = Column(Integer, nullable=True)
    threshold_pace_seconds_per_km_source = Column(String(30), nullable=True)
    threshold_pace_seconds_per_km_updated_at = Column(DateTime(timezone=True), nullable=True)
    max_hr = Column(Integer, nullable=True)
    zone2_hr_min = Column(Integer, nullable=True)
    zone2_hr_min_updated_at = Column(DateTime(timezone=True), nullable=True)
    zone2_hr_max = Column(Integer, nullable=True)
    zone2_hr_max_updated_at = Column(DateTime(timezone=True), nullable=True)
    weekly_zone2_target_min = Column(Integer, nullable=True)
    preferred_units = Column(String(20), nullable=False, server_default=text("'metric'"))
    timezone = Column(String(100), nullable=False, server_default=text("'Asia/Bangkok'"))
    week_start_day = Column(Integer, nullable=False, server_default=text("1"))
    display_name = Column(String(100), nullable=True)
    date_format = Column(String(20), nullable=False, server_default=text("'YYYY-MM-DD'"))
    strength_rpe_max = Column(Integer, nullable=True)
    aerobic_decoupling_threshold = Column(Float, nullable=True)
    ctl_days = Column(Integer, nullable=True)
    atl_days = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))


class TrainingLoadSnapshot(Base):
    """The sole persisted CTL/ATL/TSB/ACWR record for a user+date — see
    backend/services/training_load.py's daily_update()/get_snapshot_series()
    and docs/calculations/training-load.md. No other code path may compute
    and independently render these metrics; every consumer reads this row
    (computing it on a cache miss/stale formula_version, then storing it)."""

    __tablename__ = "training_load_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    snapshot_date = Column(Date, nullable=False)
    tss_for_day = Column(Integer, nullable=False)
    ctl = Column(Float, nullable=False)
    atl = Column(Float, nullable=False)
    tsb = Column(Float, nullable=False)
    # Acute:Chronic Workload Ratio, from acwr.compute_acwr() over the 35-day
    # window ending this date. Nullable — None when there isn't enough
    # trailing history yet (acwr.py's own _MIN_DAYS guard), same convention
    # every other ACWR consumer already follows.
    acwr = Column(Float, nullable=True)
    # Stamps which formula/constants produced this row (mirrors the
    # tss_method stamping pattern on Workout) — a row whose formula_version
    # doesn't match training_load._FORMULA_VERSION is treated as a cache
    # miss and recomputed, so a change to the EWMA/ACWR math can never
    # silently keep serving stale-shape rows forever.
    formula_version = Column(Text, nullable=True)
    # The per-user EWMA windows this row was computed with (issue #1366 —
    # user-tunable CTL/ATL constants). Nullable: rows predating the feature.
    # NOTE: restored after the sprint-104 merge (15db9bb1) dropped this hunk
    # while migration 3c5bf7cf48ed and training_load.daily_update()'s writes
    # survived — without these, every snapshot upsert dies with
    # CompileError: Unconsumed column names.
    ctl_days = Column(Integer, nullable=True)
    atl_days = Column(Integer, nullable=True)
    computed_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("user_id", "snapshot_date", name="uq_training_load_snapshots_user_date"),
        Index("ix_training_load_snapshots_user_date", "user_id", "snapshot_date"),
    )


class SyncJob(Base):
    __tablename__ = "sync_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source = Column(String(50), nullable=False)
    job_type = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False, server_default=text("'pending'"), default="pending")
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    activities_fetched = Column(Integer, nullable=False, server_default=text("0"), default=0)
    activities_created = Column(Integer, nullable=False, server_default=text("0"), default=0)
    activities_updated = Column(Integer, nullable=False, server_default=text("0"), default=0)
    activities_skipped = Column(Integer, nullable=False, server_default=text("0"), default=0)
    error_message = Column(Text, nullable=True)
    since_date = Column(Date, nullable=True)
    parameters = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        Index("ix_sync_jobs_user_source_started_at", "user_id", "source", "started_at"),
    )


class WorkerJobRun(Base):
    __tablename__ = "worker_job_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    job_type = Column(String(30), nullable=False)  # 'strava_sync'|'stryd_sync'|'backfill'|'banister_refit'
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    status = Column(String(10), nullable=False, server_default=text("'running'"), default="running")  # running|success|error
    phase = Column(String(30), nullable=True)
    items_synced = Column(Integer, nullable=False, server_default=text("0"), default=0)
    error = Column(Text, nullable=True)
    triggered_by = Column(String(10), nullable=False, server_default=text("'manual'"), default="manual")  # manual|schedule
    stats = Column(JSONB, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_worker_job_runs_user_started_at", "user_id", "started_at"),
        Index("ix_worker_job_runs_job_type_started_at", "job_type", "started_at"),
    )


class JobQueue(Base):
    """Neon-backed pull queue: the worker (behind home NAT) claims rows instead
    of being called over HTTP. Separate from worker_job_runs, which stays the
    execution audit trail — this table is the intent/queue. See
    backend/services/job_queue.py (repo) and backend/worker_app.py (poll loop).
    """

    __tablename__ = "job_queue"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    job_type = Column(String(40), nullable=False)  # strava_sync|stryd_sync|backfill|banister_refit|...
    payload = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status = Column(String(12), nullable=False, server_default=text("'queued'"), default="queued")  # queued|running|done|failed|cancelled
    priority = Column(Integer, nullable=False, server_default=text("0"), default=0)  # lower = sooner
    attempts = Column(Integer, nullable=False, server_default=text("0"), default=0)
    max_attempts = Column(Integer, nullable=False, server_default=text("3"), default=3)
    claimed_by = Column(String(120), nullable=True)  # worker instance id (hostname:pid)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    result = Column(JSONB, nullable=True)
    error = Column(Text, nullable=True)
    worker_job_run_id = Column(UUID(as_uuid=True), ForeignKey("worker_job_runs.id", ondelete="SET NULL"), nullable=True)
    enqueued_by = Column(String(12), nullable=True)  # web|schedule|manual
    dedupe_key = Column(String(200), nullable=True)  # skip re-enqueue while an active row shares this
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # Claim query: WHERE status='queued' ORDER BY priority, created_at.
        Index("ix_job_queue_claim", "priority", "created_at",
              postgresql_where=text("status = 'queued'")),
        # Stale reaper: WHERE status='running' AND lease_expires_at < now().
        Index("ix_job_queue_lease", "lease_expires_at",
              postgresql_where=text("status = 'running'")),
        # Dedupe lookup for active rows sharing a key.
        Index("ix_job_queue_dedupe", "dedupe_key",
              postgresql_where=text("status IN ('queued', 'running') AND dedupe_key IS NOT NULL")),
    )


class ActivityStream(Base):
    """Per-sample time-series channel data for a workout.

    One row per workout; the absence of a row is the canonical signal that a
    workout has no stream data (e.g. a manual strength session). Each channel
    column is independently nullable — a row may exist with only workout_id and
    source set.

    Worked example::

        from sqlalchemy.orm import Session
        from backend.db import engine
        from backend.models import ActivityStream

        with Session(engine) as session:
            stream = ActivityStream(
                workout_id=some_workout_uuid,
                source="strava",
                sample_interval_seconds=1,
                time_offset_seconds=[0, 1, 2, 3],
                power_w=[250, 260, 245, 255],
                heart_rate_bpm=[145, 147, 146, 148],
            )
            session.add(stream)
            session.commit()
    """

    __tablename__ = "activity_streams"

    workout_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workouts.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    sample_interval_seconds = Column(Integer, nullable=True)
    source = Column(String(20), nullable=True)
    time_offset_seconds = deferred(Column(JSONB, nullable=True))
    power_w = deferred(Column(JSONB, nullable=True))
    heart_rate_bpm = deferred(Column(JSONB, nullable=True))
    pace_seconds_per_km = deferred(Column(JSONB, nullable=True))
    cadence_spm = deferred(Column(JSONB, nullable=True))
    altitude_m = deferred(Column(JSONB, nullable=True))
    latitude = deferred(Column(JSONB, nullable=True))
    longitude = deferred(Column(JSONB, nullable=True))
    channel_attribution = deferred(Column(JSONB, nullable=True))

    __table_args__ = (
        CheckConstraint(
            "source IS NULL OR source IN ('strava', 'stryd', 'merged')",
            name="ck_activity_streams_source_values",
        ),
    )


# Valid priority and status values — referenced by the Race model and migration.
RACE_PRIORITY_VALUES = ("A", "B", "C")
RACE_STATUS_VALUES = ("planned", "done", "abandoned")
RACE_TYPE_VALUES = ("race", "checkpoint")


def _in_clause(values):
    """Build an SQL IN(...) literal from a tuple of string constants."""
    return ", ".join(f"'{v}'" for v in values)


class Race(Base):
    """A target race entry for a user.

    ``goal_pace_seconds_per_km`` is always the output of :func:`compute_goal_pace`;
    callers must never set it directly.  It is ``NULL`` when either input is
    absent, zero, or negative.
    """

    __tablename__ = "races"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    """Surrogate primary key, auto-generated UUID."""
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    """Owner of this race target; cascades to delete on user removal."""
    name = Column(String(200), nullable=False)
    """Human-readable event name (e.g. 'Boston Marathon 2026')."""
    race_date = Column(Date, nullable=False)
    """Scheduled or actual date of the race."""
    distance_km = Column(Numeric(8, 3), nullable=True)
    """Distance in km. NULL only for a duration-defined checkpoint (issue #1226)."""
    duration_seconds = Column(Integer, nullable=True)
    """Target duration in seconds — set instead of distance for a duration-defined
    checkpoint; NULL for distance-defined races/checkpoints."""
    goal_time_seconds = Column(Integer, nullable=True)
    """Target finish time in seconds; NULL if no goal is set."""
    goal_pace_seconds_per_km = Column(Integer, nullable=True)
    """Derived goal pace (goal_time_seconds / distance_km); always set via compute_goal_pace."""
    priority = Column(String(10), nullable=False, server_default=text("'A'"))
    """Race importance tier — one of RACE_PRIORITY_VALUES ('A', 'B', 'C')."""
    status = Column(String(20), nullable=False, server_default=text("'planned'"))
    """Lifecycle status — one of RACE_STATUS_VALUES ('planned', 'done', 'abandoned')."""
    race_type = Column(String(20), nullable=False, server_default="race")
    """Classification of the effort — one of RACE_TYPE_VALUES ('race', 'checkpoint')."""
    actual_time_seconds = Column(Integer, nullable=True)
    """Recorded finish time in seconds after the race is completed; NULL for future races."""
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    """Timestamp when this record was first created."""
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()"))
    """Timestamp of the most recent modification; auto-updated by the ORM on change."""

    __table_args__ = (
        Index("ix_races_user_id", "user_id"),
        CheckConstraint(
            f"priority IN ({_in_clause(RACE_PRIORITY_VALUES)})",
            name="ck_races_priority_values",
        ),
        CheckConstraint(
            f"status IN ({_in_clause(RACE_STATUS_VALUES)})",
            name="ck_races_status_values",
        ),
        CheckConstraint(
            "distance_km > 0",
            name="ck_races_distance_positive",
        ),
        CheckConstraint(
            "goal_time_seconds IS NULL OR goal_time_seconds > 0",
            name="ck_races_goal_time_positive",
        ),
        CheckConstraint(
            f"race_type IN ({_in_clause(RACE_TYPE_VALUES)})",
            name="ck_races_race_type_values",
        ),
    )

    user = relationship("User", foreign_keys=[user_id])
    checkpoints = relationship("RaceCheckpoint", back_populates="race", cascade="all, delete-orphan")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # goal_pace_seconds_per_km is always computed — never passed directly
        pace, _ = compute_goal_pace(
            self.goal_time_seconds,
            float(self.distance_km) if self.distance_km is not None else None,
        )
        self.goal_pace_seconds_per_km = pace

    def __repr__(self):
        return (
            f"<Race id={self.id} name={self.name!r} date={self.race_date} "
            f"distance_km={self.distance_km} priority={self.priority} status={self.status}>"
        )


class RaceCheckpoint(Base):
    """An intermediate milestone within a target race.

    Stores optional target fields (distance, pace, duration) so progress toward
    a goal race can be tracked in structured milestones.  All target fields are
    nullable — only ``race_id``, ``user_id``, ``label``, and ``target_date``
    are required at insert time.
    """

    __tablename__ = "race_checkpoints"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    race_id = Column(UUID(as_uuid=True), ForeignKey("races.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    label = Column(String(200), nullable=False)
    target_date = Column(Date, nullable=False)
    target_distance_km = Column(Numeric(8, 3), nullable=True)
    target_pace_seconds_per_km = Column(Integer, nullable=True)
    target_duration_seconds = Column(Integer, nullable=True)
    met = Column(Boolean, server_default=text("false"), nullable=False)
    met_override = Column(Boolean, server_default=text("false"), nullable=False)
    met_workout_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workouts.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()"),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_race_checkpoints_race_id", "race_id"),
        Index("ix_race_checkpoints_user_id", "user_id"),
    )

    race = relationship("Race", foreign_keys=[race_id], back_populates="checkpoints")
    user = relationship("User", foreign_keys=[user_id])
    met_workout = relationship("Workout", foreign_keys=[met_workout_id])

    def effective_target_pace(self):
        """Return ``(target_pace_seconds_per_km, None)`` when set.

        Returns ``(None, reason)`` when ``target_pace_seconds_per_km`` is absent,
        so callers never need to guard against an unhandled exception.
        """
        if self.target_pace_seconds_per_km is None:
            return None, "target_pace_seconds_per_km is not set for this checkpoint"
        return self.target_pace_seconds_per_km, None

    def __repr__(self):
        return (
            f"<RaceCheckpoint id={self.id} race_id={self.race_id} "
            f"label={self.label!r} target_date={self.target_date}>"
        )


class RaceCalibration(Base):
    """One calibration event per finished race: what the model predicted vs
    what the athlete actually ran, and the resulting correction factor
    (actual/predicted). The weighted blend of these rows (recency +
    distance-similarity, clamped) corrects every future finish estimate —
    the real implementation of the previously-stubbed recalibrate-from-race
    loop. See backend/services/race_calibration.py and
    docs/calculations/projection.md §3."""
    __tablename__ = "race_calibrations"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    race_id = Column(UUID(as_uuid=True), ForeignKey("races.id", ondelete="CASCADE"), nullable=False, unique=True)
    race_date = Column(Date, nullable=False)
    distance_km = Column(Numeric(8, 3), nullable=False)
    predicted_seconds = Column(Integer, nullable=False)
    actual_seconds = Column(Integer, nullable=False)
    correction = Column(Numeric(6, 4), nullable=False)  # actual / predicted, UNclamped
    source = Column(Text, nullable=False, server_default=text("'backcast'"))  # backcast | stored_prediction
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        Index("ix_race_calibrations_user_date", "user_id", "race_date"),
        CheckConstraint("predicted_seconds > 0", name="ck_race_calibrations_predicted_seconds"),
        CheckConstraint("actual_seconds > 0", name="ck_race_calibrations_actual_seconds"),
        CheckConstraint("correction > 0", name="ck_race_calibrations_correction"),
        CheckConstraint("source IN ('backcast', 'stored_prediction')", name="ck_race_calibrations_source"),
    )


class RacePrediction(Base):
    """Daily persisted race-day finish predictions — one row per race per day
    the bundle computed an estimate. Future calibrations diff the actual
    result against what was actually SHOWN to the athlete instead of a
    backcast, and the residual history is the dataset every learned
    confidence band needs (docs/calculations/README.md ML-blocker #1)."""
    __tablename__ = "race_predictions"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    race_id = Column(UUID(as_uuid=True), ForeignKey("races.id", ondelete="CASCADE"), nullable=False)
    prediction_date = Column(Date, nullable=False)
    predicted_seconds = Column(Integer, nullable=False)
    band_seconds = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("race_id", "prediction_date", name="uq_race_predictions_race_day"),
        Index("ix_race_predictions_user_race", "user_id", "race_id"),
        CheckConstraint("predicted_seconds > 0", name="ck_race_predictions_predicted_seconds"),
    )


class AthleteDurationCurve(Base):
    """Per-athlete best-effort duration curve aggregated across all run workouts.

    One row per athlete. The ``curve_data`` JSONB stores a dict keyed by
    str(duration_seconds) mapping to the best observed value at that window and
    the workout it came from. Absence of a row means no runs have been processed
    for that athlete yet.

    Worked example::

        from sqlalchemy.orm import Session
        from backend.db import engine
        from backend.models import AthleteDurationCurve
        import uuid

        with Session(engine) as session:
            curve = AthleteDurationCurve(
                user_id=some_user_uuid,
                curve_data={
                    "60": {"best_value": 270.0, "workout_id": str(uuid.uuid4()),
                           "date": "2026-01-15", "confidence": "measured"},
                    "300": {"best_value": 255.0, "workout_id": str(uuid.uuid4()),
                            "date": "2026-01-15", "confidence": "measured"},
                },
            )
            session.add(curve)
            session.commit()
    """

    __tablename__ = "athlete_duration_curves"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    curve_data = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()"))

    user = relationship("User", foreign_keys=[user_id])


def validate_weight_plan_required(start_weight_kg, goal_weight_kg):
    """Return (True, None) when required fields are present, else (None, reason).

    Mirrors the compute_goal_pace pattern: never raises, returns a 2-tuple so
    callers can distinguish success from missing-input without catching exceptions.
    """
    if start_weight_kg is None:
        return (None, "start_weight_kg is required")
    if goal_weight_kg is None:
        return (None, "goal_weight_kg is required")
    return (True, None)


class WeightPlan(Base):
    """Structured weight-goal plan: phase, target rate, and date range for one user."""

    __tablename__ = "weight_plans"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    start_date = Column(Date, nullable=False)
    start_weight_kg = Column(Numeric(6, 2), nullable=False)
    goal_weight_kg = Column(Numeric(6, 2), nullable=False)
    goal_date = Column(Date, nullable=True)
    target_rate_kg_per_week = Column(Numeric(4, 2), nullable=True)
    phase = Column(Text, nullable=False, server_default=text("'cut'"))
    active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()"))

    __table_args__ = (
        Index("ix_weight_plans_user_id", "user_id"),
    )


class SleepRecord(Base):
    """One night of sleep data from an external source (e.g. health_sync_csv)."""

    __tablename__ = "sleep_records"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    sleep_date = Column(Date, nullable=False)
    start_at = Column(DateTime(timezone=True), nullable=False)
    end_at = Column(DateTime(timezone=True), nullable=False)
    total_sleep_minutes = Column(Integer, nullable=False)
    time_in_bed_minutes = Column(Integer, nullable=False)
    awake_minutes = Column(Integer, nullable=True)
    light_minutes = Column(Integer, nullable=True)
    deep_minutes = Column(Integer, nullable=True)
    rem_minutes = Column(Integer, nullable=True)
    sleep_score = Column(Integer, nullable=True)
    sleep_efficiency = Column(Numeric(5, 2), nullable=True)
    source = Column(Text, nullable=False)
    device = Column(Text, nullable=True)
    external_id = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()"))

    __table_args__ = (
        UniqueConstraint("user_id", "external_id", name="uq_sleep_records_user_external_id"),
        Index("ix_sleep_records_user_sleep_date", "user_id", "sleep_date"),
    )


TAPER_SHAPE_VALUES = ("linear", "step", "exponential")


class TrainingPlan(Base):
    """Training plan with ramp-up and taper-down configuration parameters."""

    __tablename__ = "training_plans"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(Text, nullable=False)
    # Fraction, e.g. 0.05 = 5%/week (see backend/services/load_plan.py). Was
    # Numeric(6, 2)/absolute TSS-per-week in the old client-only schedule
    # preview; widened+repurposed for the race-anchored Session Load Plan.
    ramp_rate = Column(Numeric(6, 4), nullable=True)
    taper_start = Column(Numeric(6, 2), nullable=True)
    taper_length = Column(Numeric(6, 2), nullable=True)
    taper_shape = Column(Text, nullable=True)
    # Peak-hold length in weeks between the end of the ramp and the start of
    # the taper. Raising this LOWERS peak load (it shortens the ramp) — see
    # docs/calculations/load-plan.md.
    hold_weeks = Column(Integer, nullable=False, server_default=text("4"))
    # "Cut 30% every 4th week" deload toggle — see load_plan.py's
    # DELOAD_CUT_FRACTION / compute_load_plan(deload_enabled=...).
    deload_enabled = Column(Boolean, nullable=False, server_default=text("false"))
    # Which week of the 4-week cycle the deload lands on (1-4): first deload
    # at this week_index, then every 4 weeks (4 → 4, 8, 12; 2 → 2, 6, 10).
    # NOTE: restored after the sprint-104 merge (15db9bb1) silently dropped
    # this hunk while the DB column (migration fe28c4815e7e) and every reader
    # (main.py _plan_rules_dict, plan_suggestions.assemble_facts) survived —
    # without it those endpoints 500 with AttributeError.
    deload_start_week = Column(Integer, nullable=False, server_default=text("4"))
    # Cached computed Plan-tab bundle + the signature it was computed for
    # (see GET /api/plan/computed). Recomputed when the signature changes.
    computed_cache = Column(JSONB, nullable=True)
    computed_signature = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()"))

    __table_args__ = (
        Index("ix_training_plans_user_id", "user_id"),
        CheckConstraint(
            "taper_shape IS NULL OR taper_shape IN ('linear', 'step', 'exponential')",
            name="ck_training_plans_taper_shape",
        ),
    )


class PlannedLoad(Base):
    """One planned-TSS value per calendar date (issue #1102)."""

    __tablename__ = "planned_load"

    date = Column(Date, primary_key=True)
    planned_tss = Column(Numeric(8, 2), nullable=False)


class StrengthSession(Base):
    """A logged heavy-strength training session (issue #1142).

    Supports two load-capture patterns:
    - sets × reps × load: provide sets, reps, load; leave session_rpe/duration_minutes null.
    - session-RPE × duration: provide session_rpe, duration_minutes; leave sets/reps/load null.
    Both patterns may coexist in the same row.
    """

    __tablename__ = "strength_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_date = Column(Date, nullable=False)
    exercise_name = Column(String(200), nullable=True)
    sets = Column(Integer, nullable=True)
    reps = Column(Integer, nullable=True)
    load = Column(Numeric(8, 2), nullable=True)
    load_unit = Column(String(10), nullable=True)
    session_rpe = Column(Integer, nullable=True)
    duration_minutes = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        Index("ix_strength_sessions_user_date", "user_id", "session_date"),
        CheckConstraint("sets IS NULL OR sets > 0", name="ck_strength_sessions_sets_positive"),
        CheckConstraint("reps IS NULL OR reps > 0", name="ck_strength_sessions_reps_positive"),
        CheckConstraint("load IS NULL OR load >= 0", name="ck_strength_sessions_load_non_negative"),
        CheckConstraint(
            "session_rpe IS NULL OR (session_rpe >= 1 AND session_rpe <= 10)",
            name="ck_strength_sessions_rpe_range",
        ),
        CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes > 0",
            name="ck_strength_sessions_duration_positive",
        ),
        CheckConstraint(
            "load_unit IS NULL OR load_unit IN ('kg', 'lbs')",
            name="ck_strength_sessions_load_unit_values",
        ),
    )


class PlyoSession(Base):
    """Plyometric training session with foot-contact volume tracking (issue #1143)."""

    __tablename__ = "plyo_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_date = Column(Date, nullable=False)
    exercise_name = Column(String(200), nullable=True)
    foot_contacts = Column(Integer, nullable=False)
    plyo_phase = Column(String(20), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "foot_contacts >= 0",
            name="ck_plyo_sessions_foot_contacts_non_negative",
        ),
        CheckConstraint(
            "plyo_phase IN ('intro', 'build', 'maintain')",
            name="ck_plyo_sessions_plyo_phase_values",
        ),
    )


class EconomyCeilingSnapshot(Base):
    """Per-user per-date economy stimulus and lagged ceiling bonus (issue #1149)."""

    __tablename__ = "economy_ceiling_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    snapshot_date = Column(Date, nullable=False)
    economy_stimulus = Column(Float, nullable=False, server_default=text("0.0"))
    ceiling_bonus = Column(Float, nullable=False, server_default=text("0.0"))
    computed_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("user_id", "snapshot_date", name="uq_economy_ceiling_snapshots_user_date"),
        Index("ix_economy_ceiling_snapshots_user_date", "user_id", "snapshot_date"),
        CheckConstraint("economy_stimulus >= 0", name="ck_economy_ceiling_snapshots_stimulus_non_negative"),
        CheckConstraint("ceiling_bonus >= 0", name="ck_economy_ceiling_snapshots_bonus_non_negative"),
    )


class UserBanisterParams(Base):
    """Per-user fitted Banister model parameters with versioned history (issue #1204).

    Each call to save_banister_params inserts a new row; old rows are never
    overwritten, enabling a full audit trail of refits.
    """

    __tablename__ = "user_banister_params"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tau1 = Column(Float, nullable=False)
    tau2 = Column(Float, nullable=False)
    k1 = Column(Float, nullable=False)
    k2 = Column(Float, nullable=False)
    fitted_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_user_banister_params_user_fitted_at", "user_id", "fitted_at"),
    )


class SummaryCache(Base):
    """Durable (Neon-backed) L2 cache for computed summary/performance payloads.

    Mirrors the in-memory ``_SUMMARY_CACHE`` (L1) in ``backend/main.py``: one row
    per ``(user_id, cache_key)``, invalidated when the stored ``signature`` no
    longer matches the recomputed signature. Persisting to Neon means a server
    restart (which wipes L1) does not force a cold recompute — the first request
    after restart reads straight from this table.

    ``cache_key`` values in use: ``"weekly"``, ``"monthly:<...>"``,
    ``"performance"`` — the same keys the callers already pass to get/put.
    """

    __tablename__ = "summary_cache"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    cache_key = Column(Text, primary_key=True, nullable=False)
    signature = Column(Text, nullable=False)
    payload = Column(JSONB, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class PlannedSession(Base):
    """A hand-entered planned training session for the new Plan tab.

    Distinct from Projection's synthetic ramp/taper load model (TrainingPlan /
    PlannedLoad). Link-only: ``matched_workout_id`` points at the reconciled
    ``workouts`` row that fulfilled this planned session — the workout stays its
    own row and the Log tab is unchanged.
    """

    __tablename__ = "planned_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    planned_date = Column(Date, nullable=False, index=True)
    # run | strength | plyo | rest
    session_type = Column(String(20), nullable=False)
    name = Column(String(200), nullable=True)
    # blocks[] for runs / exercises[] for strength·plyo; null for rest
    structure = Column(JSONB, nullable=True)
    notes = Column(Text, nullable=True)
    # planned | missed | needs_review | done_auto | done_manual
    status = Column(String(20), nullable=False, server_default=text("'planned'"))
    matched_workout_id = Column(
        UUID(as_uuid=True),
        ForeignKey("workouts.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_planned_sessions_user_date", "user_id", "planned_date"),
    )


class ExerciseCatalog(Base):
    """Global catalog of exercises with body-part ratios, LLM- or manually classified.

    name is normalized (stripped, lowercased) to dedup across users and workout sources.
    body_parts: [{part: str, ratio: float}, ...] — ratios sum to ~1.0.
    source: 'llm' | 'manual'
    """

    __tablename__ = "exercise_catalog"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name = Column(String(200), nullable=False, unique=True, index=True)
    body_parts = Column(JSONB, nullable=False, default=list)
    source = Column(String(20), nullable=False, default="llm")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


INJURY_KIND_VALUES = ("injury", "illness", "niggle")


class InjuryLog(Base):
    """Injury / illness / niggle log entry for one user."""

    __tablename__ = "injury_log"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(20), nullable=False)
    body_area = Column(String(100), nullable=True)
    severity = Column(Integer, nullable=False)
    started_on = Column(Date, nullable=False)
    ended_on = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)

    __table_args__ = (
        CheckConstraint("kind IN ('injury', 'illness', 'niggle')", name="ck_injury_log_kind"),
        CheckConstraint("severity IN (1, 2, 3)", name="ck_injury_log_severity"),
        CheckConstraint("ended_on IS NULL OR ended_on >= started_on", name="ck_injury_log_ended_after_started"),
        Index("ix_injury_log_user_started_on", "user_id", "started_on"),
    )


class LlmGeneration(Base):
    """Cached LLM-generated text payloads keyed by (user, surface, input_signature).

    Re-used when inputs haven't changed; invalidated by signature mismatch.
    Created by backend/services/llm.py get_or_generate().
    """

    __tablename__ = "llm_generations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    surface = Column(String(100), nullable=False)
    input_signature = Column(String(64), nullable=False)
    payload = Column(JSONB, nullable=False)
    model = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("user_id", "surface", "input_signature", name="uq_llm_generations_user_surface_sig"),
        Index("ix_llm_generations_user_surface_sig", "user_id", "surface", "input_signature"),
    )


class VerdictHistory(Base):
    """Persisted snapshot of each day's training verdict and its inputs.

    Written (upserted) whenever compute_verdict runs for the current day so
    there is a durable record of what the app advised vs what happened.
    Historical dates are never touched — only today's computation updates
    this row. The unique constraint enforces one row per user+date.
    """

    __tablename__ = "verdict_history"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    verdict_date = Column(Date, nullable=False)
    verdict = Column(String(20), nullable=False)
    modifiers = Column(JSONB, nullable=True)
    readiness = Column(Float, nullable=True)
    ctl = Column(Float, nullable=True)
    atl = Column(Float, nullable=True)
    tsb = Column(Float, nullable=True)
    acwr = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("user_id", "verdict_date", name="uq_verdict_history_user_date"),
        Index("ix_verdict_history_user_date", "user_id", "verdict_date"),
    )


class BodyMeasurement(Base):
    """Periodic body composition measurement (waist circumference and/or body-fat %)."""

    __tablename__ = "body_measurements"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    measure_date = Column(Date, nullable=False)
    waist_cm = Column(Numeric(5, 1), nullable=True)
    body_fat_pct = Column(Numeric(4, 1), nullable=True)
    source = Column(String(20), nullable=False, server_default=text("'manual'"))
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("user_id", "measure_date", name="uq_body_measurements_user_date"),
        Index("ix_body_measurements_user_date", "user_id", "measure_date"),
        CheckConstraint("source IN ('manual', 'imported')", name="ck_body_measurements_source"),
    )


class PerformanceScoreHistory(Base):
    """Persisted daily endurance/speed scores with formula version stamps (issue #1361/#1365).

    One row per (user, date, formula_version) — upserted each time scores are
    computed so there is a durable series to compute block deltas from without
    relying on the in-request trend[] recomputation.
    """

    __tablename__ = "performance_score_history"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    score_date = Column(Date, nullable=False)
    endurance = Column(Float, nullable=True)
    speed = Column(Float, nullable=True)
    formula_version = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint(
            "user_id", "score_date", "formula_version",
            name="uq_performance_score_history_user_date_version",
        ),
        Index("ix_performance_score_history_user_date", "user_id", "score_date"),
    )


class RunFormMetrics(Base):
    """Per-run Stryd running-dynamics extracted from stryd_activities.form_metrics (issue #1368).

    Key mapping (verified against live Stryd calendar API, 2026-06-17 via stryd_sync.py):
        form_metrics["ground_contact_time_ms"]  -> gct_ms
        form_metrics["leg_spring_stiffness"]    -> lss_kn_m  (kN/m, Stryd native unit)
        form_metrics["vertical_oscillation_cm"] -> vertical_oscillation_cm
        form_metrics["cadence_spm"]             -> cadence_spm
        stryd_activities.avg_power_w            -> power_w
    """

    __tablename__ = "run_form_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    workout_id = Column(UUID(as_uuid=True), ForeignKey("workouts.id", ondelete="SET NULL"), nullable=True)
    stryd_activity_pk = Column(UUID(as_uuid=True), ForeignKey("stryd_activities.id", ondelete="CASCADE"), nullable=False)
    run_date = Column(Date, nullable=False)
    gct_ms = Column(Numeric(8, 2), nullable=True)
    lss_kn_m = Column(Numeric(8, 4), nullable=True)
    vertical_oscillation_cm = Column(Numeric(6, 2), nullable=True)
    cadence_spm = Column(Numeric(6, 2), nullable=True)
    power_w = Column(Numeric(6, 1), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)

    __table_args__ = (
        UniqueConstraint("stryd_activity_pk", name="uq_run_form_metrics_stryd_activity_pk"),
        Index("ix_run_form_metrics_user_run_date", "user_id", "run_date"),
    )


class PredictionSnapshot(Base):
    """Daily persisted projection forecast for forecast-vs-actual accuracy evaluation.

    One row per user per day — written on the first projection computation of the day
    (later same-day recomputes do NOT overwrite, preserving the morning forecast).
    The payload JSON contains per-race predicted finish times with race ids, projected
    CTL at race date, peak CTL + peak week, and formula_version. See issue #1362.
    """
    __tablename__ = "prediction_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    snapshot_date = Column(Date, nullable=False)
    payload = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("user_id", "snapshot_date", name="uq_prediction_snapshots_user_date"),
        Index("ix_prediction_snapshots_user_date", "user_id", "snapshot_date"),
    )


class MuscleLoadDaily(Base):
    """Per-day TSS-weighted load per muscle group per source (issue #1367).

    Rows are recomputed-idempotent: the writer deletes existing rows for the
    (user, date, source) triple and inserts fresh ones so re-running never
    double-counts. The unique constraint enforces one row per
    (user, date, muscle_group, source).
    """

    __tablename__ = "muscle_load_daily"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    load_date = Column(Date, nullable=False)
    muscle_group = Column(String(30), nullable=False)
    load = Column(Numeric(10, 4), nullable=False)
    source = Column(String(20), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "load_date", "muscle_group", "source",
            name="uq_muscle_load_daily_user_date_group_source",
        ),
        CheckConstraint(
            "source IN ('strength', 'run', 'plyo')",
            name="ck_muscle_load_daily_source",
        ),
        Index("ix_muscle_load_daily_user_date", "user_id", "load_date"),
    )


class GapFinding(Base):
    """Gap-analyzer finding: one persistent row per (user, week_start, code) (issue #1370).

    code      — stable string id for the rule that fired (e.g. 'no_recent_plyo')
    severity  — 1=note, 2=recommend, 3=priority
    evidence  — machine-readable list [{metric, value, threshold, window}]
    target    — nullable: muscle group or session type
    status    — 'active' | 'accepted' | 'dismissed' (accept/dismiss in sprint 108)
    Recomputing upserts evidence/recommendation/computed_at but PRESERVES status.
    """

    __tablename__ = "gap_findings"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    week_start = Column(Date, nullable=False)
    code = Column(String(80), nullable=False)
    severity = Column(Integer, nullable=False)
    recommendation = Column(Text, nullable=False)
    evidence = Column(JSONB, nullable=False, default=list)
    target = Column(String(100), nullable=True)
    computed_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(20), nullable=False, server_default=text("'active'"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    # Suppression metadata (issue #1377)
    dismissed_at = Column(DateTime(timezone=True), nullable=True)
    dismissed_severity = Column(Integer, nullable=True)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    accepted_evidence_hash = Column(String(64), nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "week_start", "code", name="uq_gap_findings_user_week_code"),
        CheckConstraint("severity IN (1, 2, 3)", name="ck_gap_findings_severity"),
        CheckConstraint(
            "status IN ('active', 'accepted', 'dismissed')",
            name="ck_gap_findings_status",
        ),
        Index("ix_gap_findings_user_week_start", "user_id", "week_start"),
    )


_RACE_DISTANCE_VALUES = ("5k", "10k", "half", "marathon")


class PerformanceGoal(Base):
    """Race goal set by the user — one active goal per user at a time (issue #1501)."""

    __tablename__ = "performance_goals"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    race_distance = Column(String(20), nullable=False)
    target_time = Column(Integer, nullable=False)
    race_date = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    active = Column(Boolean, nullable=False, server_default=text("true"))

    __table_args__ = (
        CheckConstraint(
            "race_distance IN ('5k', '10k', 'half', 'marathon')",
            name="ck_performance_goals_race_distance_values",
        ),
        Index("ix_performance_goals_user_id", "user_id"),
    )


class WeeklyCoachMessage(Base):
    """Persisted weekly coaching message — one record per (user, ISO week) (issue #1504).

    Generated by the weekly job from coach_plan.build_plan_state() + projection
    engine outputs.  The unique constraint on (user_id, for_week) enforces
    idempotency: re-running the job for the same ISO week updates the existing
    record rather than inserting a duplicate.
    """

    __tablename__ = "weekly_coach_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    for_week = Column(String(8), nullable=False)
    generated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    text = Column(Text, nullable=False)
    plan_state_snapshot = Column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "for_week", name="uq_weekly_coach_messages_user_week"),
        Index("ix_weekly_coach_messages_user_generated_at", "user_id", "generated_at"),
    )
