from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("How it works", callback_data="help"),
                InlineKeyboardButton("My status", callback_data="status"),
            ],
            [InlineKeyboardButton("Supported links", callback_data="platforms")],
        ]
    )


def card_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="start")]])


def status_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("How it works", callback_data="help"),
                InlineKeyboardButton("Back", callback_data="start"),
            ]
        ]
    )


def done_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("My status", callback_data="status"),
                InlineKeyboardButton("How it works", callback_data="help"),
            ]
        ]
    )
