import json
import logging
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    FIELDS = ("request_id", "method", "path", "status_code", "duration_ms", "user_id")

    def format(self, record):
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update({name: getattr(record, name) for name in self.FIELDS if hasattr(record, name)})
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)
