from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ParserAction(BaseModel):
    player: Optional[str] = None
    action: Optional[str] = None
    order: Optional[int] = None
    amount: Optional[float] = None
    amount_to: Optional[float] = None
    amount_ratio: Optional[str] = None
    amount_pct: Optional[float] = None
    is_all_in: Optional[bool] = False
    raw_text: Optional[str] = None


class ActionsByStreet(BaseModel):
    preflop: List[ParserAction] = Field(default_factory=list)
    flop: List[ParserAction] = Field(default_factory=list)
    turn: List[ParserAction] = Field(default_factory=list)
    river: List[ParserAction] = Field(default_factory=list)


class BlindSchema(BaseModel):
    sb: Optional[float] = 0.5
    bb: Optional[float] = 1.0


class ParserSnapshot(BaseModel):
    is_strategy_query: bool = False
    is_new_hand: Optional[bool] = None
    hero_position: Optional[str] = None
    villain_position: Optional[str] = None
    hero_hole_cards: List[str] = Field(default_factory=list)
    board_cards: List[str] = Field(default_factory=list)
    street: Optional[str] = None
    hero_stack_bb: Optional[float] = None
    villain_stack_bb: Optional[float] = None
    pot_bb: Optional[float] = None
    actions: ActionsByStreet = Field(default_factory=ActionsByStreet)
    blinds: BlindSchema = Field(default_factory=BlindSchema)
    missing_fields: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    confidence: Optional[float] = None


def validate_parser_snapshot(data):
    if hasattr(ParserSnapshot, "model_validate"):
        return ParserSnapshot.model_validate(data)
    return ParserSnapshot.parse_obj(data)
