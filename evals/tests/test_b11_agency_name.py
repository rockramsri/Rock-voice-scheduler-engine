"""B11 — spoken/copy strings take the agency name, not a hardcoded brand."""

from data.db import agency_display_name
from voice.agents.offer_agent import build_offer_agent
from evals.run_voice import FAKE_OFFER
from copy import deepcopy


def test_agency_display_name_from_join_and_row():
    assert agency_display_name({"agencies": {"name": "Harbor Home"}}) == "Harbor Home"
    assert agency_display_name({"name": "Harbor Home", "timezone": "UTC"}) == "Harbor Home"
    assert agency_display_name({}) == "the agency"


def test_offer_agent_instructions_use_passed_agency_name():
    offer = deepcopy(FAKE_OFFER)
    agent = build_offer_agent(offer, agency_name="Harbor Home Care")
    blob = str(agent.instructions)
    assert "Harbor Home Care" in blob
    assert ("Rock" + "ram") not in blob
