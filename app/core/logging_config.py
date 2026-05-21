import logging

from app.core.config import get_settings


def configure_app_logging() -> None:
    settings = get_settings()
    uvicorn_error_logger = logging.getLogger("uvicorn.error")
    app_logger = logging.getLogger("app")
    app_logger.handlers.clear()

    # Uvicorn's access handler uses a formatter that only works for its own
    # 5-field access log records. Reusing it for application logs raises
    # formatting errors during startup and request logging.
    handlers = [*uvicorn_error_logger.handlers]
    unique_handlers: list[logging.Handler] = []
    seen_handler_ids: set[int] = set()

    for handler in handlers:
        handler_id = id(handler)
        if handler_id in seen_handler_ids:
            continue
        seen_handler_ids.add(handler_id)
        unique_handlers.append(handler)

    if unique_handlers:
        for handler in unique_handlers:
            app_logger.addHandler(handler)
    else:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
        app_logger.addHandler(handler)

    app_logger.setLevel(logging.DEBUG if settings.APP_DEBUG else logging.INFO)
    app_logger.propagate = False
