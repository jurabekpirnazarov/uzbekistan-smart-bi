"""Business profiles (ml/profiles/*.yaml) with Pydantic validation.

A new business type is a new YAML file — no code change (CLAUDE.md rule 11).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

PROFILES_DIR = Path(__file__).resolve().parents[1] / "profiles"
FEATURES_FILE = Path(__file__).resolve().parents[1] / "features" / "definitions.yaml"
# Features produced by the forecasting job (Phase 5), usable as optional factors.
FORECAST_FEATURES = {"forecast_population_growth", "forecast_business_growth"}


class Factor(BaseModel):
    feature: str
    weight: float = Field(gt=0, le=1)
    direction: Literal["+", "-"] = "+"
    label: str
    enabled: bool = True


class DisplayName(BaseModel):
    en: str
    uz: str
    ru: str


class Profile(BaseModel):
    business_type: str
    display_name: DisplayName
    keywords: list[str] = []
    min_budget_uzs: int = Field(ge=0)
    default_level: Literal["region", "district"] = "district"
    factors: list[Factor]
    normalization: Literal["percentile", "minmax_winsorized"] = "percentile"
    optional_factors: list[Factor] = []

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> Profile:
        total = sum(f.weight for f in self.factors)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"{self.business_type}: factor weights sum to {total:.3f}, expected 1.0")
        names = [f.feature for f in self.factors + self.optional_factors]
        if len(names) != len(set(names)):
            raise ValueError(f"{self.business_type}: duplicate factor features")
        return self

    def active_factors(self) -> list[Factor]:
        return self.factors + [f for f in self.optional_factors if f.enabled]


class Targets(BaseModel):
    feature_tags: dict[str, str]
    targets: dict[str, dict[str, float]]


def known_features() -> set[str]:
    return set(yaml.safe_load(FEATURES_FILE.read_text(encoding="utf-8"))) | FORECAST_FEATURES


def load_profile_file(path: Path, features: set[str] | None = None) -> Profile:
    profile = Profile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    features = features if features is not None else known_features()
    unknown = [f.feature for f in profile.factors + profile.optional_factors if f.feature not in features]
    if unknown:
        raise ValueError(f"{path.name}: unknown features {unknown} (not in ml/features/definitions.yaml)")
    return profile


@lru_cache
def load_profiles(directory: Path = PROFILES_DIR) -> dict[str, Profile]:
    features = known_features()
    out = {}
    for path in sorted(directory.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        p = load_profile_file(path, features)
        out[p.business_type] = p
    return out


@lru_cache
def load_targets(directory: Path = PROFILES_DIR) -> Targets:
    return Targets.model_validate(yaml.safe_load((directory / "_targets.yaml").read_text(encoding="utf-8")))
