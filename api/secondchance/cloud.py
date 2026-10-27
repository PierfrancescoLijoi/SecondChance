"""Cloud seam (ADR-023): one image, the adapters follow SECONDCHANCE_CLOUD.

`aws` is the default and keeps every existing code path; `azure` switches queues, objects, models,
identity, e-mail and real-time delivery to their Azure equivalents. Locally nothing is set and the
Compose services (ElasticMQ, SeaweedFS, mock OIDC, Mailpit) stay in charge.
"""

import os
from functools import lru_cache


def is_azure() -> bool:
    return os.environ.get("SECONDCHANCE_CLOUD", "aws") == "azure"


@lru_cache
def azure_credential():
    """Managed identity inside Container Apps; the developer's `az login` elsewhere.

    AZURE_CLIENT_ID selects the identity when several are attached: the app attaches a pull-only
    identity next to its working one, so an unqualified request would be ambiguous.
    """
    from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

    if os.environ.get("IDENTITY_ENDPOINT") or os.environ.get("MSI_ENDPOINT"):
        return ManagedIdentityCredential(client_id=os.environ.get("AZURE_CLIENT_ID"))
    return DefaultAzureCredential(exclude_interactive_browser_credential=True)


def bearer(scope: str) -> str:
    return azure_credential().get_token(scope).token
