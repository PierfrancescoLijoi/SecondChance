from mcp_gateway.service import handle


def gateway(event: dict, context) -> dict:
    return handle(event)
