"""Channel operations CLI — terminal remote-control for phone + messaging.

  python -m channels.cli status              SIP trunks, rules, config checks
  python -m channels.cli call +1XXXXXXXXXX   outbound call from the agent
  python -m channels.cli sms +1XXX "text"    Twilio SMS (needs A2P in the US)
  python -m channels.cli whatsapp +1X "hi"   WhatsApp (sandbox: join first)
  python -m channels.cli textbelt +1X "hi"   instant SMS, no A2P (capped)
  python -m channels.cli serve               run the inbound-message webhook
  python -m channels.cli link-sms            point the number at PUBLIC_BASE_URL/sms
  python -m channels.cli provision           create SIP resources for a fresh number
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from channels import outbound, sms, telephony, webhook
from shared import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-18s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)


def _link_sms() -> None:
    """One-time: set the Twilio number's inbound-SMS webhook to our server."""
    if not config.PUBLIC_BASE_URL:
        raise SystemExit("Set PUBLIC_BASE_URL first (the `ngrok http 8787` https URL)")
    from twilio.rest import Client

    client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
    numbers = client.incoming_phone_numbers.list(phone_number=config.TWILIO_PHONE_NUMBER)
    if not numbers:
        raise SystemExit(f"{config.TWILIO_PHONE_NUMBER} not found on this Twilio account")
    url = f"{config.PUBLIC_BASE_URL}/sms"
    numbers[0].update(sms_url=url, sms_method="POST")
    print(f"linked: inbound SMS for {config.TWILIO_PHONE_NUMBER} -> {url}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="channels", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="show SIP resources + config checks")
    call = sub.add_parser("call", help="place an outbound call")
    call.add_argument("to", help="destination in E.164, e.g. +19295550123")
    for name, help_text in (
        ("sms", "send a Twilio SMS (US needs A2P registration)"),
        ("whatsapp", "send a WhatsApp message (sandbox: recipient joins first)"),
        ("textbelt", "send an instant capped SMS via TextBelt (no A2P)"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("to", help="destination in E.164")
        p.add_argument("text", nargs="+", help="message body")
    sub.add_parser("serve", help="run the inbound-message webhook server")
    sub.add_parser("link-sms", help="point the Twilio number at this webhook")
    sub.add_parser("provision", help="create SIP resources for a fresh number")
    args = parser.parse_args()

    if args.cmd == "status":
        asyncio.run(telephony.status())
    elif args.cmd == "call":
        print(asyncio.run(outbound.place_call(args.to)))
    elif args.cmd == "sms":
        print(asyncio.run(sms.send_sms(args.to, " ".join(args.text))))
    elif args.cmd == "whatsapp":
        print(asyncio.run(sms.send_whatsapp(args.to, " ".join(args.text))))
    elif args.cmd == "textbelt":
        print(asyncio.run(sms.send_textbelt(args.to, " ".join(args.text))))
    elif args.cmd == "serve":
        webhook.serve()
    elif args.cmd == "link-sms":
        _link_sms()
    elif args.cmd == "provision":
        asyncio.run(telephony.provision())


if __name__ == "__main__":
    main()
