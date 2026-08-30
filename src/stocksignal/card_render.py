"""Rendering an opportunity card: for the phone, and for the desk.

Two audiences, two formats, and the split matters. The Telegram card is read
standing up and answers "is this worth opening the laptop for". The markdown
card is read at the desk with the chart open and has to survive being
disagreed with, so it shows its working, every level, every page citation,
every reason a target was not placed.

WHY THE WARNINGS SIT ABOVE THE NUMBERS on the phone. A caveat printed under a
price target is a caveat nobody reads, because the number is what the eye lands
on and the thumb is already moving. The two warnings that matter here, a stop
sitting on the ratio's own support, and a target placed with no growth
direction researched, both describe a card that LOOKS more actionable than it
is. They go first or they do not work.

WHY NEITHER FORMAT PRINTS A TOTAL. The ledger is not scored. Page 131: "A big
elevating factor can counter a deprecating factor." Rendering "4 elevating, 2
deprecating" would be a score in all but name, and would invite exactly the
arithmetic the course refuses to do. Big factors are marked with an exclamation
and the reader weighs them.
"""

from __future__ import annotations

from stocksignal.opportunity import BIG, OpportunityCard

MESSAGE_LIMIT = 4096
"""Telegram's hard cap, enforced with an unhelpful error if you cross it."""


def escape(text: str) -> str:
    """Telegram's HTML parse mode only cares about these three."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _upside(card: OpportunityCard) -> str:
    pct = card.upside_pct
    return f"{pct:+.0f}%" if pct is not None else "n/a"


def render_card_telegram(card: OpportunityCard) -> str:
    """One stock, phone-sized: the plan, the numbers, the ledger, the caveats."""
    lines: list[str] = []

    critical = [
        w for w in card.warnings if w.startswith("STOP SITS ON") or w.startswith("No growth")
    ]
    for warning in critical:
        # Split on ". " and not ".", because the warning quotes a ratio and a
        # bare full stop cut "THE 3.1:1 RATIO" down to "THE 3." on the phone.
        lines.append(f"⚠️ <b>{escape(warning.split('. ')[0])}.</b>")
    if critical:
        lines.append("")

    lines.append(f"<b>{escape(card.ticker)}</b> · {card.close:,.2f} · {card.as_of.isoformat()}")
    lines.append(f"<i>{escape(card.play_type)} play · {escape(card.direction.describe())}</i>")

    # ONE LINE ON THE PHONE, AND IT IS ALWAYS PRESENT. A card that silently
    # dropped the balance reading whenever there was none would look exactly
    # like one where the sheet came back clean, which is the failure this
    # project has now written down in three separate modules.
    if card.balance is None:
        lines.append("<i>Balance sheet: no reading</i>")
    else:
        lines.append(f"<i>Balance sheet: {escape(card.balance.summary)}</i>")
    lines.append("")

    if card.target.price is not None:
        lines.append(
            f"<b>Target {card.target.price:,.2f}</b> ({_upside(card)}) "
            f"· {escape(card.target.method)} method · {card.target.horizon_months}mo"
        )
    else:
        why = card.target.basis[0] if card.target.basis else "not placed"
        lines.append(f"<b>Target: none</b>, {escape(why)}")

    stop_text = f"{card.hard_stop:,.2f}" if card.hard_stop is not None else "none available"
    ratio = f"{card.reward_risk:.1f}:1" if card.reward_risk is not None else "n/a"
    lines.append(f"Stop {escape(stop_text)} · reward:risk {ratio}")

    if card.position.shares_at_cap is not None:
        loss = card.position.max_loss_at_cap
        risk = f", risking {loss:,.0f}" if loss is not None else ""
        lines.append(f"At the 20% cap: {card.position.shares_at_cap:,} shares{escape(risk)}")

    lines.append("")
    lines.append(f"<b>Plan.</b> {escape(card.entry_plan)}")

    if card.elevating:
        lines.append("")
        lines.append("<b>For</b>")
        lines += [f"  + {escape(f.describe())}" for f in card.elevating]
    if card.deprecating:
        lines.append("")
        lines.append("<b>Against</b>")
        lines += [f"  − {escape(f.describe())}" for f in card.deprecating]

    if any(f.weight == BIG for f in card.elevating + card.deprecating):
        lines.append("")
        lines.append("<i>! marks a big factor. Not a tally, a big one can cancel a small one.</i>")

    lines.append("")
    lines.append("<i>Candidate only. Every entry and exit is your decision.</i>")

    message = "\n".join(lines)
    if len(message) > MESSAGE_LIMIT:
        message = message[: MESSAGE_LIMIT - 20].rstrip() + "\n<i>… truncated.</i>"
    return message


def render_card_markdown(card: OpportunityCard) -> str:
    """The desk version: the 7-Step Test skeleton, page 133, with all the working.

    Step order follows the course rather than importance-to-the-reader, because
    step 2 (risk versus reward) is a reject gate. Page 23: "the stock has no
    upward potential with a downward potential of 2 dollars... it won't make
    sense to take a position here with this setup." Putting the factors first
    would let a persuasive ledger argue past a setup the geometry already
    disqualified.
    """
    out: list[str] = []
    add = out.append

    add(f"# {card.ticker}, {card.close:,.2f} on {card.as_of.isoformat()}")
    add("")
    add(f"**{card.play_type.title()} play.** {card.direction.describe()}.")
    add("")

    if card.direction.basis:
        add("Direction research:")
        for item in card.direction.basis:
            add(f"- {item}")
        if card.direction.source:
            add(f"- source: {card.direction.source}")
        add("")

    # PLACED BEFORE STEP 1, AND OUTSIDE THE COURSE'S NUMBERING ON PURPOSE. The
    # 7-Step Test never asks about the balance sheet, so this cannot be a step
    # without inventing one. It goes first rather than last because the source
    # it comes from treats it as the thing you check before you get interested:
    # "I've seen more investors do their dough buying cheap stocks without
    # checking the balance sheet than any other mistake."
    add("## The balance sheet, which the 7-Step Test does not ask about")
    add("")
    if card.balance is None:
        add(
            "**No reading.** This card is a price and geometry reading only, with nothing "
            "said about cash, debt, or what the assets are made of. Build the readings with "
            "`scripts/balance_sweep.py --store data/balance.json`."
        )
    else:
        out.extend(card.balance.detail())
    add("")
    add(
        "_Not part of the 7-Step Test, and deliberately not folded into the ledger below: "
        "page 131 lets a big elevating factor counter a deprecating one, and a balance sheet "
        "flag is not the sort of thing three good factors should be able to talk past._"
    )
    add("")

    add("## 1. Timeframe")
    add("")
    add(
        f"Six-month horizon on daily bars, per page 219. Median anchor {card.median:,.2f}."
        if card.median is not None
        else "Six-month horizon. No median anchor."
    )
    for item in card.median_basis:
        add(f"- {item}")
    add("")

    add("## 2. Risk vs reward")
    add("")
    support = f"{card.support:,.2f}" if card.support is not None else "none found"
    resistance = f"{card.resistance:,.2f}" if card.resistance is not None else "none found"
    add(f"- Nearest support: {support}")
    add(f"- Nearest resistance: {resistance}")
    if card.target.price is not None:
        add(
            f"- Target: **{card.target.price:,.2f}** ({_upside(card)}), {card.target.method} method"
        )
    else:
        add("- Target: **not placed**")
    for item in card.target.basis:
        add(f"  - {item}")
    if card.reward_risk is not None:
        add(f"- Reward:risk **{card.reward_risk:.2f}:1** (target − price) : (price − support)")
    else:
        add("- Reward:risk: not computable")
    add("")

    if card.alternate_target is not None:
        add("<details><summary>The other method, for comparison</summary>")
        add("")
        if card.alternate_target.price is not None:
            add(f"{card.alternate_target.method}: {card.alternate_target.price:,.2f}")
        else:
            add(f"{card.alternate_target.method}: not placed")
        for item in card.alternate_target.basis:
            add(f"- {item}")
        add("")
        add("</details>")
        add("")

    add("## 3. Elevating and deprecating factors")
    add("")
    add("Not scored, and deliberately so, page 131: a big elevating factor can counter a")
    add("deprecating one. `!` marks a big factor.")
    add("")
    add("| For | Against |")
    add("| --- | --- |")
    rows = max(len(card.elevating), len(card.deprecating))
    for i in range(rows):
        left = card.elevating[i].describe() if i < len(card.elevating) else ""
        right = card.deprecating[i].describe() if i < len(card.deprecating) else ""
        add(f"| {left} | {right} |")
    add("")

    add("## 4. Long term")
    add("")
    add(
        "The 180 SMA reading in the ledger above IS the long-term context "
        "(pages 88 to 90). Nothing else here looks past it."
    )
    add("")

    add("## 5. News catalysts")
    add("")
    add("Not readable from price bars. Page 133 step 5 asks it and this card cannot answer it.")
    add("")

    add("## 6. Analyst price target")
    add("")
    add("Not fetched. Pages 145 to 150 treat the gap to consensus as a real factor.")
    add("")

    add("## 7. Is it worth it?")
    add("")
    add(f"**Entry plan.** {card.entry_plan}")
    add("")
    add(f"**Exit plan.** {card.exit_plan}")
    add("")
    if card.position.shares_at_cap is not None:
        # Built as one string rather than appended in pieces: `add` writes a
        # markdown LINE, so continuing a sentence with a second call put the
        # risk figure on its own line beginning with a comma.
        sizing = (
            f"**Sizing.** At the {card.position.account_size:,.0f} account, the 20% cap is "
            f"{card.position.max_position_value:,.0f} → {card.position.shares_at_cap:,} shares"
        )
        if card.position.max_loss_at_cap is not None:
            sizing += f", risking {card.position.max_loss_at_cap:,.0f} to the stop."
        else:
            sizing += "."
        add(sizing)
    else:
        add(f"**Sizing.** {card.position.note}")
    add("")

    add("## Warnings")
    add("")
    for warning in card.warnings:
        add(f"- {warning}")
    add("")
    add("---")
    add("")
    add("Candidate only. Nothing here is advice, and every entry and exit is your decision.")
    return "\n".join(out)


def render_cards_telegram(cards: list[OpportunityCard], limit: int = 3) -> str:
    """Several cards in one message, newest-scoring first.

    Capped low on purpose. A phone message with eight full cards in it is a
    document, and a document is not read on a phone, it is dismissed. The
    overflow line names how many were dropped so the cap never masquerades as
    "that was everything".
    """
    if not cards:
        return "<b>stocksignal</b>\nNothing passed today."

    chunks = [render_card_telegram(card) for card in cards[:limit]]
    message = "\n\n· · ·\n\n".join(chunks)
    if len(cards) > limit:
        message += f"\n\n<i>and {len(cards) - limit} more in the digest.</i>"
    if len(message) > MESSAGE_LIMIT:
        message = message[: MESSAGE_LIMIT - 20].rstrip() + "\n<i>… truncated.</i>"
    return message
