from application_sdk.clients.sql import BaseSQLClient
from application_sdk.handlers.sql import BaseSQLHandler
from application_sdk.observability.logger_adaptor import get_logger

logger = get_logger(__name__)


class MySQLHandler(BaseSQLHandler):
    """
    Handler for MySQL metadata extraction.
    """

    def __init__(self, sql_client: BaseSQLClient | None = None):
        # MySQL typically uses single database mode
        super().__init__(sql_client, multidb=False)
