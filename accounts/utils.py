def normalize_whatsapp_number(phone_number, default_country_code="254"):
    """
    Return a phone number in WhatsApp Click-to-Chat format.

    Kenyan local numbers such as 0712345678 are converted to
    254712345678. International numbers are preserved after
    removing common formatting characters.
    """
    if not phone_number:
        return ""

    number = str(phone_number).strip()

    number = (
        number.replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )

    if number.startswith("+"):
        number = number[1:]

    if number.startswith("0"):
        number = f"{default_country_code}{number[1:]}"

    return number
