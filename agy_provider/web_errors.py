"""Send stable panel errors through AstrBot's string-only iframe bridge."""

WEB_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def web_error(code, message, status_code):
    from astrbot.api.web import error_response

    return error_response(f"[AGY:{code}] {message}", status_code=status_code,
                          data={"code": code}, headers=WEB_HEADERS)
