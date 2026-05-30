import uuid
from sqlalchemy import BigInteger, Boolean, Column, Index, Integer, String, Numeric, Float, Date, DateTime, ForeignKey, UniqueConstraint, CheckConstraint, text, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name = Column(String(100), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


class WeightEntry(Base):
    __tablename__ = "weight_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    weight_kg = Column(Numeric(5, 2), nullable=False)
    recorded_date = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (UniqueConstraint("user_id", "recorded_date", name="uq_weight_entries_user_date"),)


class Habit(Base):
    __tablename__ = "habits"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String(100), nullable=False)
    display_order = Column(Integer, server_default=text("0"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    archived_at = Column(DateTime(timezone=True), nullable=True)


class HabitLog(Base):
    __tablename__ = "habit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    habit_id = Column(UUID(as_uuid=True), ForeignKey("habits.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    logged_date = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (UniqueConstraint("habit_id", "logged_date", name="uq_habit_logs_habit_date"),)


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
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        CheckConstraint("tss IS NULL OR tss >= 0", name="ck_workouts_tss_non_negative"),
        CheckConstraint("tss_source IS NULL OR tss_source IN ('manual', 'calculated')", name="ck_workouts_tss_source_values"),
        CheckConstraint("source IS NULL OR source IN ('strava', 'manual')", name="ck_workouts_source_values"),
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


class StrydCredentials(Base):
    __tablename__ = "stryd_credentials"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    stryd_email = Column(String(255), nullable=False)
    stryd_password_encrypted = Column(Text, nullable=False)
    session_token = Column(Text, nullable=True)
    session_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    athlete_id = Column(BigInteger, nullable=True)
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
    device_name = Column(String(255), nullable=True)
    external_id = Column(String(255), nullable=True)
    is_stryd_synced = Column(Boolean, server_default=text("false"), nullable=False)
    raw_payload = Column(JSONB, nullable=False)
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
