"""Pydantic-skeemat API:n pyyntöjen ja vastausten validointiin."""
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


# ---------- Exercise ----------
class ExerciseBase(BaseModel):
    name: str
    category: str | None = None
    muscle_group: str | None = None
    is_main_lift: bool = False
    sport: str | None = None
    equipment: str | None = None
    per_hand: bool = False
    default_sets: int = 3
    default_reps: int = 10
    unit: str = "kg"
    description: str | None = None
    notes: str | None = None


class ExerciseCreate(ExerciseBase):
    pass


class ExerciseUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    muscle_group: str | None = None
    is_main_lift: bool | None = None
    sport: str | None = None
    equipment: str | None = None
    per_hand: bool | None = None
    default_sets: int | None = None
    default_reps: int | None = None
    unit: str | None = None
    notes: str | None = None


class ExerciseOut(ExerciseBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


# ---------- ProgramExercise ----------
class ProgramExerciseBase(BaseModel):
    exercise_id: int
    order_index: int = 0
    target_sets: int = 3
    target_reps: int = 5
    target_weight: float | None = None
    rest_seconds: int | None = None
    target_rir: float | None = None
    rep_scheme: str | None = None
    percent_scheme: str | None = None
    notes: str | None = None


class ProgramExerciseCreate(ProgramExerciseBase):
    pass


class ProgramExerciseOut(ProgramExerciseBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exercise: ExerciseOut


# ---------- ProgramDay ----------
class ProgramDayBase(BaseModel):
    order_index: int = 0
    day_type: str = "train"  # train | rest
    label: str | None = None


class ProgramDayCreate(ProgramDayBase):
    exercises: list[ProgramExerciseCreate] = Field(default_factory=list)


class ProgramDayUpdate(BaseModel):
    order_index: int | None = None
    day_type: str | None = None
    label: str | None = None


class ProgramDayOut(ProgramDayBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exercises: list[ProgramExerciseOut] = Field(default_factory=list)


# ---------- Program ----------
class ProgramBase(BaseModel):
    name: str
    profile_id: int | None = None
    schedule_type: str = "cycle"  # cycle | weekly
    description: str | None = None
    goal: str | None = None
    is_active: bool = True
    auto_progress: bool = False
    start_date: date | None = None
    end_date: date | None = None


class ProgramCreate(ProgramBase):
    days: list[ProgramDayCreate] = Field(default_factory=list)


class ProgramUpdate(BaseModel):
    name: str | None = None
    schedule_type: str | None = None
    description: str | None = None
    goal: str | None = None
    is_active: bool | None = None
    auto_progress: bool | None = None


class ProgramOut(ProgramBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    days: list[ProgramDayOut] = Field(default_factory=list)


# ---------- SetLog ----------
class SetLogBase(BaseModel):
    set_index: int = 0
    reps: int = 0
    weight: float = 0.0
    rir: float | None = None
    completed: bool = True
    notes: str | None = None


class SetLogCreate(SetLogBase):
    pass


class SetLogOut(SetLogBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ---------- WorkoutExercise ----------
class WorkoutExerciseBase(BaseModel):
    exercise_id: int
    order_index: int = 0
    done: bool = False
    missed_reps: int = 0
    notes: str | None = None


class WorkoutExerciseCreate(WorkoutExerciseBase):
    sets: list[SetLogCreate] = Field(default_factory=list)


class WorkoutExerciseOut(WorkoutExerciseBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exercise: ExerciseOut
    sets: list[SetLogOut] = Field(default_factory=list)


# ---------- WorkoutSession ----------
class WorkoutSessionBase(BaseModel):
    session_date: date | None = None
    profile_id: int | None = None
    program_day_id: int | None = None
    name: str | None = None
    bodyweight: float | None = None
    duration_min: int | None = None
    kcal_burned: float | None = None
    feeling: str | None = None
    feeling_note: str | None = None
    status: str = "completed"
    notes: str | None = None


class WorkoutSessionCreate(WorkoutSessionBase):
    exercises: list[WorkoutExerciseCreate] = Field(default_factory=list)


class WorkoutSessionUpdate(BaseModel):
    session_date: date | None = None
    name: str | None = None
    bodyweight: float | None = None
    duration_min: int | None = None
    kcal_burned: float | None = None
    feeling: str | None = None
    feeling_note: str | None = None
    status: str | None = None
    notes: str | None = None


class WorkoutSessionOut(WorkoutSessionBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    exercises: list[WorkoutExerciseOut] = Field(default_factory=list)


# ---------- Engine / laskenta ----------
class SchemeConversionIn(BaseModel):
    current_weight: float
    current_sets: int = 4
    current_reps: int = 5
    target_sets: int = 4
    target_reps: int = 8
    current_rir: float | None = None
    target_rir: float | None = None
    increment: float = 2.5


class SchemeConversionOut(BaseModel):
    estimated_1rm: float
    current_weight: float
    suggested_weight: float
    suggested_weight_rounded: float
    from_scheme: str
    to_scheme: str
    note: str


# ---------- Profile ----------
class ProfileBase(BaseModel):
    name: str
    sex: str | None = None
    birthdate: date | None = None
    height_cm: float | None = None
    color: str | None = None
    creatine: bool = False
    notes: str | None = None


class ProfileCreate(ProfileBase):
    pass


class ProfileUpdate(BaseModel):
    name: str | None = None
    sex: str | None = None
    birthdate: date | None = None
    height_cm: float | None = None
    color: str | None = None
    creatine: bool | None = None
    notes: str | None = None


class ProfileOut(ProfileBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


# ---------- BodyEntry ----------
class BodyEntryBase(BaseModel):
    entry_date: date | None = None
    bodyweight: float | None = None
    body_fat_pct: float | None = None
    sleep_hours: float | None = None
    sleep_score: float | None = None
    hrv: float | None = None
    resting_hr: float | None = None
    kcal: float | None = None
    steps: float | None = None
    water_l: float | None = None
    notes: str | None = None


class BodyEntryCreate(BodyEntryBase):
    pass


class BodyEntryOut(BodyEntryBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    profile_id: int


# ---------- CardioSession ----------
class CardioSessionBase(BaseModel):
    session_date: date | None = None
    activity: str = "juoksumatto"
    duration_min: float | None = None
    kcal: float | None = None
    avg_hr: float | None = None
    distance_km: float | None = None
    notes: str | None = None


class CardioSessionCreate(CardioSessionBase):
    pass


class CardioSessionOut(CardioSessionBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    profile_id: int


# ---------- Measurement ----------
class MeasurementBase(BaseModel):
    entry_date: date | None = None
    site: str
    value_cm: float


class MeasurementCreate(MeasurementBase):
    pass


class MeasurementOut(MeasurementBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    profile_id: int


# ---------- Food ----------
class FoodBase(BaseModel):
    name: str
    category: str | None = None
    is_favorite: bool = False
    kcal: float = 0.0
    protein_g: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0
    fiber_g: float = 0.0
    sugar_g: float = 0.0
    sodium_mg: float = 0.0
    default_grams: float | None = None


class FoodCreate(FoodBase):
    pass


class FoodUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    is_favorite: bool | None = None
    kcal: float | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None
    fiber_g: float | None = None
    sugar_g: float | None = None
    sodium_mg: float | None = None
    default_grams: float | None = None


class FoodOut(FoodBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


class FoodLogCreate(BaseModel):
    entry_date: date | None = None
    food_id: int
    grams: float = 100.0


class FoodLogUpdate(BaseModel):
    grams: float


class FoodLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    profile_id: int
    entry_date: date
    grams: float
    food: FoodOut


# ---------- Meal (oma ravintokokonaisuus) ----------
class MealItemIn(BaseModel):
    food_id: int
    grams: float = 100.0


class MealItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    grams: float
    food: FoodOut


class MealCreate(BaseModel):
    name: str
    items: list[MealItemIn] = Field(default_factory=list)


class MealOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    profile_id: int
    name: str
    items: list[MealItemOut] = Field(default_factory=list)
