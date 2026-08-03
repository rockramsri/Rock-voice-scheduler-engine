"""LiveKit SIP plumbing — inspect and provision trunks + dispatch rules.

status() shows every SIP resource on the connected LiveKit project and flags
config mismatches (the top cause of inbound calls ringing into an empty
room). provision() creates the three resources for a FRESH number; it never
deletes or edits existing ones, so it cannot break another project's trunk.
"""

from __future__ import annotations

from livekit import api

from shared import config


async def status() -> None:
    """Print SIP trunks + dispatch rules and check them against our config."""
    lk = api.LiveKitAPI()  # reads the LIVEKIT_* env that shared.config loaded
    try:
        inbound = (await lk.sip.list_inbound_trunk(api.ListSIPInboundTrunkRequest())).items
        outbound = (await lk.sip.list_outbound_trunk(api.ListSIPOutboundTrunkRequest())).items
        rules = (await lk.sip.list_dispatch_rule(api.ListSIPDispatchRuleRequest())).items
    finally:
        await lk.aclose()

    print(f"livekit project : {config.LIVEKIT_URL}")
    print(f"twilio number   : {config.TWILIO_PHONE_NUMBER or 'MISSING'}")
    print(f"worker agent    : {config.AGENT_NAME or '(auto-dispatch)'}\n")

    for trunk in inbound:
        print(f"inbound trunk   {trunk.sip_trunk_id}  {trunk.name!r}  numbers={list(trunk.numbers)}")
    for trunk in outbound:
        ours = "  <- LIVEKIT_SIP_OUTBOUND_TRUNK_ID" if trunk.sip_trunk_id == config.SIP_OUTBOUND_TRUNK_ID else ""
        print(f"outbound trunk  {trunk.sip_trunk_id}  {trunk.name!r}  address={trunk.address}{ours}")
    dispatch_agents: list[str] = []
    for rule in rules:
        agents = [a.agent_name for a in rule.room_config.agents] if rule.HasField("room_config") else []
        dispatch_agents += agents
        print(f"dispatch rule   {rule.sip_dispatch_rule_id}  {rule.name!r}  trunks={list(rule.trunk_ids)}  agents={agents}")

    print()
    if not inbound:
        print("!! no inbound trunk — inbound calls cannot arrive (see `provision`)")
    if config.AGENT_NAME and config.AGENT_NAME in dispatch_agents:
        print(f"ok: dispatch targets {config.AGENT_NAME!r} — run `python -m voice.entry dev`, "
              f"then call {config.TWILIO_PHONE_NUMBER}")
    elif config.AGENT_NAME:
        print(f"!! AGENT_NAME={config.AGENT_NAME!r} is not targeted by any dispatch rule — "
              "inbound calls will NOT reach this worker")
    if not config.SIP_OUTBOUND_TRUNK_ID:
        print("!! LIVEKIT_SIP_OUTBOUND_TRUNK_ID missing — outbound calls disabled")


async def provision() -> None:
    """Create inbound trunk, dispatch rule, and outbound trunk for a fresh number."""
    number = config.TWILIO_PHONE_NUMBER
    if not number:
        raise SystemExit("TWILIO_PHONE_NUMBER is required to provision")
    agent = config.AGENT_NAME or "rock-agent"

    lk = api.LiveKitAPI()
    try:
        inbound = (await lk.sip.list_inbound_trunk(api.ListSIPInboundTrunkRequest())).items
        claimed = next((t for t in inbound if number in t.numbers), None)
        if claimed and claimed.name != "rock-inbound":
            raise SystemExit(
                f"{number} is already claimed by trunk {claimed.sip_trunk_id} ({claimed.name!r}); "
                "reuse that setup (see README) instead of provisioning a duplicate"
            )
        trunk = claimed or await lk.sip.create_inbound_trunk(api.CreateSIPInboundTrunkRequest(
            trunk=api.SIPInboundTrunkInfo(name="rock-inbound", numbers=[number]),
        ))
        print(f"inbound trunk : {trunk.sip_trunk_id}")

        rules = (await lk.sip.list_dispatch_rule(api.ListSIPDispatchRuleRequest())).items
        rule = next((r for r in rules if r.name == "rock-dispatch"), None)
        rule = rule or await lk.sip.create_dispatch_rule(api.CreateSIPDispatchRuleRequest(
            name="rock-dispatch",
            trunk_ids=[trunk.sip_trunk_id],
            rule=api.SIPDispatchRule(
                dispatch_rule_individual=api.SIPDispatchRuleIndividual(room_prefix="call-"),
            ),
            room_config=api.RoomConfiguration(
                agents=[api.RoomAgentDispatch(agent_name=agent)],
            ),
        ))
        print(f"dispatch rule : {rule.sip_dispatch_rule_id} -> agent {agent!r} (rooms call-*)")

        if config.SIP_OUTBOUND_TRUNK_ID:
            print(f"outbound trunk: {config.SIP_OUTBOUND_TRUNK_ID} (already configured)")
        elif not (config.TWILIO_TERMINATION_URI and config.TWILIO_SIP_USERNAME):
            print("outbound trunk: skipped — set TWILIO_TERMINATION_URI / TWILIO_SIP_USERNAME / "
                  "TWILIO_SIP_PASSWORD and rerun")
        else:
            out = await lk.sip.create_outbound_trunk(api.CreateSIPOutboundTrunkRequest(
                trunk=api.SIPOutboundTrunkInfo(
                    name="rock-outbound",
                    address=config.TWILIO_TERMINATION_URI,
                    numbers=[number],
                    auth_username=config.TWILIO_SIP_USERNAME,
                    auth_password=config.TWILIO_SIP_PASSWORD,
                ),
            ))
            print(f"outbound trunk: {out.sip_trunk_id} — put this in .env as LIVEKIT_SIP_OUTBOUND_TRUNK_ID")
    finally:
        await lk.aclose()
