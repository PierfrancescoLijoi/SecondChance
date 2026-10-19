param(
  [ValidateSet("demo", "pilot")][string]$Environment = "demo",
  [Parameter(Mandatory = $true)][string]$AlarmEmail,
  [string]$Profile = "secondchance-admin",
  [string]$GitHubRepository = "",
  # Claude is sold through AWS Marketplace and needs a payment method; eu.amazon.nova-lite-v1:0 does not.
  [string]$BedrockModel = ""
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$commands = @{}
# Native Terraform: it refreshes `aws login` and SSO sessions itself; the container sees ~/.aws read-only.
foreach ($command in @("aws", "docker", "git", "bash", "terraform")) {
  $resolved = Get-Command "$command" -ErrorAction SilentlyContinue
  if (-not $resolved) { throw "Required command was not found: $command" }
  $commands[$command] = $resolved
}
$bash = $commands["bash"]
$env:AWS_PROFILE = $Profile
$env:SECONDCHANCE_ALARM_EMAIL = $AlarmEmail
$env:SECONDCHANCE_GITHUB_REPOSITORY = $GitHubRepository
if ($BedrockModel) { $env:SECONDCHANCE_BEDROCK_MODEL = $BedrockModel }
# IAM Identity Center needs AWS Organizations, which turns a Free plan account into a paid one; a
# console-session profile (`aws login`, AWS CLI 2.32+) works on any account, with no access keys.
if ((aws configure get sso_session --profile $Profile) -or (aws configure get sso_start_url --profile $Profile)) {
  aws sso login --profile $Profile
} else {
  aws login --profile $Profile
}
if ($LASTEXITCODE -ne 0) { throw "AWS sign-in failed for profile $Profile" }
& $bash.Source "$root/scripts/connect-aws.sh" $Environment
if ($LASTEXITCODE -ne 0) { throw "AWS setup failed with exit code $LASTEXITCODE" }
