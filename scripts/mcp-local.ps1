param(
  [Parameter(Mandatory = $true)][string]$TenantId,
  [Parameter(Mandatory = $true)][string]$Subject,
  [ValidateSet("coordinator", "org_admin", "volunteer", "center_staff", "platform_admin")]
  [string]$Role = "coordinator"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
docker compose exec -T `
  -e "SECONDCHANCE_MCP_TENANT_ID=$TenantId" `
  -e "SECONDCHANCE_MCP_SUBJECT=$Subject" `
  -e "SECONDCHANCE_MCP_ROLE=$Role" `
  mcp-gateway python -m mcp_gateway.mcp_server
