# AUTO-GENERATED from contract/app.pkl — DO NOT EDIT MANUALLY.
# To regenerate: pkl eval -m . contract/app.pkl
from application_sdk.testing.e2e.sql_app import SQLAppE2ETest  # type: ignore[attr-defined]


class MySQLGeneratedE2EBase(SQLAppE2ETest):
    connector_short_name = "mysql"
    argo_package_name = "@atlan/mysql"
    argo_template_name = "atlan-mysql"
    app_service_url = "http://mysql.mysql-app.svc.cluster.local"
