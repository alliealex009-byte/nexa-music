from pyrogram.types import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup


def owner_panel() -> Markup:
    return Markup(
        [
            [Btn("📊 Stats", callback_data="own:stats")],
            [Btn("❌ Close", callback_data="close")],
        ]
    )
