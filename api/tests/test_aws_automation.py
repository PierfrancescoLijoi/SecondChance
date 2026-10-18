from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_connect_aws_bootstraps_preflights_deploys_and_verifies() -> None:
    script = (ROOT / "scripts" / "connect-aws.sh").read_text()

    assert "get-caller-identity" in script
    assert "get-inference-profile" in script
    assert "models[].modelArn" in script
    assert "non-EU destination" in script
    assert "bedrock-runtime converse" in script
    assert "amazon.titan-embed-text-v2:0" in script
    assert "describe-orderable-db-instance-options" in script
    assert "AccountLimit.ConcurrentExecutions" in script
    assert "bootstrap" in script
    assert 'bash "$ROOT/scripts/deploy.sh" "$ENVIRONMENT"' in script
    assert 'bash "$ROOT/scripts/verify-aws.sh" "$ENVIRONMENT"' in script


def test_deploy_and_verification_cover_demo_rag_through_external_gateway() -> None:
    deploy = (ROOT / "scripts" / "deploy.sh").read_text()
    verify = (ROOT / "scripts" / "verify-aws.sh").read_text()
    lambda_handlers = (ROOT / "api" / "secondchance" / "aws_lambda.py").read_text()

    assert "demo-seed" in deploy
    assert "load_demo_documents" in lambda_handlers
    assert "mcp-gateway" in verify
    assert "knowledge_search" in verify
    assert "hits" in verify
    assert "runtime-check" in verify
    assert "router" in verify
    assert "embedding_dimensions" in verify
    assert "guardrail" in verify
    # botocore retries a sync invoke on read timeout: migrations and seeds must not run twice
    assert deploy.count("aws lambda invoke --cli-read-timeout 900") == 2
    assert "aws lambda invoke --cli-read-timeout 300" in verify
    # aws.exe and python.exe cannot open MSYS /tmp paths when MSYS_NO_PATHCONV is set
    for script in (deploy, verify):
        assert 'TMPDIR=$(cygpath -m "${TMPDIR:-/tmp}")' in script
    # Lambda rejects the OCI image index that buildx attestations produce
    assert "--provenance=false" in deploy
    assert "bedrock_model_id=$SECONDCHANCE_BEDROCK_MODEL" in deploy


def test_windows_entrypoint_uses_git_bash_without_persisting_credentials() -> None:
    script = (ROOT / "scripts" / "connect-aws.ps1").read_text()

    assert "AWS_ACCESS_KEY_ID" not in script
    assert "AWS_SECRET_ACCESS_KEY" not in script
    assert "connect-aws.sh" in script
    assert "SECONDCHANCE_ALARM_EMAIL" in script
    assert '@("aws", "docker", "git", "bash", "terraform")' in script
    # Free plan: no AWS Organizations, so no IAM Identity Center; console sessions instead of keys
    assert "aws login --profile $Profile" in script
    assert "aws sso login --profile $Profile" in script
    assert "$env:SECONDCHANCE_BEDROCK_MODEL = $BedrockModel" in script  # one model from preflight to Lambda
    assert 'Get-Command "$command"' in script


def test_terraform_defines_operational_dashboard_and_scaling_ceiling() -> None:
    root = ROOT / "infra" / "terraform" / "modules" / "secondchance"
    observability = (root / "observability.tf").read_text()
    compute = (root / "compute.tf").read_text()
    variables = (root / "variables.tf").read_text()

    assert 'resource "aws_cloudwatch_dashboard" "operations"' in observability
    assert 'resource "aws_cloudwatch_metric_alarm" "function_throttles"' in observability
    assert 'resource "aws_cloudwatch_metric_alarm" "api_latency"' in observability
    orchestration = (root / "orchestration.tf").read_text()
    realtime = (root / "realtime.tf").read_text()
    assert 'resource "aws_sfn_state_machine" "agents"' in orchestration
    assert 'type     = "STANDARD"' in orchestration
    assert 'resource "aws_apigatewayv2_api" "realtime"' in realtime
    assert 'variable "otel_exporter_otlp_endpoint"' in variables
    assert "OTEL_EXPORTER_OTLP_ENDPOINT" in compute
    assert '"demo-seed"' in compute
    assert '"runtime-check"' in compute


def test_emulation_builds_the_very_images_deploy_pushes() -> None:
    def build_lines(script: str) -> list[str]:
        lines = (ROOT / "scripts" / script).read_text().splitlines()
        tar = next(line.strip() for line in lines if line.strip().startswith("tar -c"))
        build = next(line.strip() for line in lines if "docker build --platform" in line)
        return [tar, build.split(" -t ")[0]]  # the tag differs, nothing else may

    assert build_lines("emulate-aws.sh") == build_lines("deploy.sh")
    assert "--provenance=false" in build_lines("deploy.sh")[1]
