from sqlalchemy import BigInteger, Boolean, Column, Index, Integer, LargeBinary, String, Numeric, Float, Date, DateTime, Time, ForeignKey, UniqueConstraint, CheckConstraint, text, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name = Column(String(100), nullable=False, unique=True)
    email = Column(String(255), nullable=True)
    is_admin = Column(Boolean, nullable=False, server_default=text("false"))
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
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


class Habit(Base):
    __tablename__ = "habits"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    tracking_type = Column(String(50), nullable=False, server_default=text("'daily_checkmark'"))
    weekly_target = Column(Numeric(10, 2), nullable=True)
    unit = Column(String(50), nullable=True)
    auto_fill_source = Column(String(100), nullable=True)
    icon = Column(String(100), nullable=True)
    color = Column(String(20), nullable=True)
    sort_order = Column(Integer, nullable=False, server_default=text("0"))
    is_archived = Column(Boolean, nullable=False, server_default=text("false"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=True)
    # Legacy columns kept for backward-compat with existing API code
    display_order = Column(Integer, server_default=text("0"), nullable=False)
    archived_at = Column(DateTime(timezone=True), nullable=True)


class HabitLog(Base):
    """Habit log entries. For daily_checkmark habits, one row per day checked (value=1). For weekly_count/minutes/quantity habits, one row per logged event with the contributed value. Week aggregation done at read time by summing values where log_week_start matches."""

    __tablename__ = "habit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    habit_id = Column(UUID(as_uuid=True), ForeignKey("habits.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    log_date = Column(Date, nullable=False)
    log_week_start = Column(Date, nullable=False)
    value = Column(Numeric(10, 4), nullable=False, server_default=text("1"))
    notes = Column(Text, nullable=True)
    source = Column(String(50), nullable=False, server_default=text("'manual'"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("habit_id", "log_date", name="uq_habit_logs_habit_log_date"),
        Index("ix_habit_logs_habit_id_log_week_start", "habit_id", "log_week_start"),
    )


class Workout(Base):
    __tablename__ = "workouts"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    workout_date = Column(Date, nullable=False)
    name = Column(String(200), nullable=False)
    workout_type = Column(String(50), nullable=False)
    remarks = Column(Text, nullable=True)
    tss = Column(Float, nullable=True)
    tss_source = Column(String(20), nullable=True)
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
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        CheckConstraint("tss IS NULL OR tss >= 0", name="ck_workouts_tss_non_negative"),
        CheckConstraint("tss_source IS NULL OR tss_source IN ('manual', 'calculated', 'stryd', 'power', 'pace', 'hr', 'duration_only')", name="ck_workouts_tss_source_values"),
        CheckConstraint("source IS NULL OR source IN ('manual', 'strava', 'stryd', 'strava,stryd', 'stryd,strava', 'both')", name="ck_workouts_source_values"),
        CheckConstraint("distance_km IS NULL OR distance_km >= 0", name="ck_workouts_distance_non_negative"),
        CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0", name="ck_workouts_duration_non_negative"),
        CheckConstraint("avg_hr IS NULL OR (avg_hr >= 20 AND avg_hr <= 250)", name="ck_workouts_avg_hr_range"),
        CheckConstraint("max_hr IS NULL OR (max_hr >= 20 AND max_hr <= 250)", name="ck_workouts_max_hr_range"),
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
    lap_type = Column(String(10), nullable=True, server_default=text("'auto'"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("workout_id", "split_index", name="uq_workout_splits_workout_split_index"),
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
    raw_payload = Column(JSONB, nullable=False)
    # Full-capture blobs — everything Strava exposes per activity (decide what to
    # surface later). detail_payload = /activities/{id}; streams_payload = its /streams.
    detail_payload = Column(JSONB, nullable=True)
    streams_payload = Column(JSONB, nullable=True)
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
    form_metrics = Column(JSONB, nullable=True)
    power_zones = Column(JSONB, nullable=True)
    splits = Column(JSONB, nullable=True)
    raw_payload = Column(JSONB, nullable=False)
    synced_at = Column(DateTime(timezone=True), server_default=text("now()"), nullable=False)

    __table_args__ = (
        Index("ix_stryd_activities_user_start_time", "user_id", "start_time"),
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
    threshold_hr = Column(Integer, nullable=True)
    threshold_pace_seconds_per_km = Column(Integer, nullable=True)
    max_hr = Column(Integer, nullable=True)
    zone2_hr_min = Column(Integer, nullable=True)
    zone2_hr_max = Column(Integer, nullable=True)
    weekly_zone2_target_min = Column(Integer, nullable=True)
    preferred_units = Column(String(20), nullable=False, server_default=text("'metric'"))
    timezone = Column(String(100), nullable=False, server_default=text("'Asia/Bangkok'"))
    week_start_day = Column(Integer, nullable=False, server_default=text("1"))
    display_name = Column(String(100), nullable=True)
    date_format = Column(String(20), nullable=False, server_default=text("'YYYY-MM-DD'"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))


class TrainingLoadSnapshot(Base):
    __tablename__ = "training_load_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    snapshot_date = Column(Date, nullable=False)
    tss_for_day = Column(Integer, nullable=False)
    ctl = Column(Float, nullable=False)
    atl = Column(Float, nullable=False)
    tsb = Column(Float, nullable=False)
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
