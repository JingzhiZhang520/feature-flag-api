from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

NAME_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$"
USER_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_.@:-]*$"


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateFlag(InputModel):
    name: str = Field(min_length=1, max_length=100, pattern=NAME_PATTERN)
    description: str = Field(default="", max_length=1000, pattern=r"^[^\x00]*$")
    default_enabled: StrictBool


class SetDefault(InputModel):
    default_enabled: StrictBool


class SetOverride(InputModel):
    enabled: StrictBool


class FlagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str
    description: str
    default_enabled: bool


class OverrideResponse(BaseModel):
    flag_name: str
    user_id: str
    enabled: bool


class Evaluation(BaseModel):
    model_config = ConfigDict(frozen=True)
    flag_name: str
    user_id: str
    enabled: bool
    source: Literal["default", "override"]
