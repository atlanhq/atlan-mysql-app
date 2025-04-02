import json
from typing import Any, Dict, Union


def parse_credentials_extra(credentials: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse the 'extra' field from credentials, handling both string and dict inputs.

    Args:
        credentials (Dict[str, Any]): Credentials dictionary containing an 'extra' field

    Returns:
        Dict[str, Any]: Parsed extra field as a dictionary

    Raises:
        ValueError: If the extra field contains invalid JSON
    """
    extra: Union[str, Dict[str, Any]] = credentials.get("extra", {})

    if isinstance(extra, str):
        try:
            return json.loads(extra)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in credentials extra field: {e}")

    return extra  # We know it's a Dict[str, Any] due to the Union type and str check
