from logging import getLogger
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# from: https://gist.github.com/norton120/22242eadb80bf2cf1dd54a961b151c61


logger = getLogger(__name__)


class MemGPTBase(BaseModel):
    """Base schema for MemGPT schemas (does not include model provider schemas, e.g. OpenAI)"""

    model_config = ConfigDict(
        # allows you to use the snake or camelcase names in your code (ie user_id or userId)
        populate_by_name=True,
        # allows you do dump a sqlalchemy object directly (ie PersistedAddress.model_validate(SQLAdress)
        from_attributes=True,
        # throw errors if attributes are given that don't belong
        extra="forbid",
    )

    def __id_prefix__(self):
        raise NotImplementedError("All schemas must have an __id_prefix__ attribute!")

    @classmethod
    def generate_id_field(cls, prefix: Optional[str] = None) -> "Field":
        prefix = prefix or cls.__id_prefix__
        return Field(
            ...,
            description=cls._id_description(prefix),
            pattern=cls._id_regex_pattern(prefix),
            examples=[cls._id_example(prefix)],
        )

    @classmethod
    def _id_regex_pattern(cls, prefix: str):
        """generates the regex pattern for a given id"""
        return (
            r"^" + prefix + r"-"  # prefix string
            r"[a-fA-F0-9]{8}-"  # 8 hexadecimal characters
            r"[a-fA-F0-9]{4}-"  # 4 hexadecimal characters
            r"[a-fA-F0-9]{4}-"  # 4 hexadecimal characters
            r"[a-fA-F0-9]{4}-"  # 4 hexadecimal characters
            r"[a-fA-F0-9]{12}$"  # 12 hexadecimal characters
        )

    @classmethod
    def _id_example(cls, prefix: str):
        """generates an example id for a given prefix"""
        return [prefix + "-123e4567-e89b-12d3-a456-426614174000"]

    @classmethod
    def _id_description(cls, prefix: str):
        """generates a factory function for a given prefix"""
        return f"The human-friendly ID of the {prefix.capitalize()}"

    @field_validator("id", check_fields=False, mode="before")
    @classmethod
    def allow_bare_uuids(cls, v, values):
        """to ease the transition to stripe ids,
        we allow bare uuids and convert them with a warning
        """
        _ = values  # for SCA
        if isinstance(v, UUID):
            logger.warning("Bare UUIDs are deprecated, please use the full prefixed id!")
            return f"{cls.__id_prefix__}-{v}"
        return v
