# Adds the AWS Lambda Runtime Interface Emulator to an image built exactly as scripts/deploy.sh
# builds it; nothing else changes. The emulator is AWS's release binary from GitHub, pinned by
# checksum (no anonymous ECR Public pull, which CI runners get throttled on).
#   docker build --build-arg BASE=secondchance-lambda:worker -t secondchance-lambda-emulator:worker infra/emulation
ARG BASE
FROM ${BASE}
ADD --chmod=755 --checksum=sha256:6b1e686e62ab2baf5759c412c4864276ef2a88b094fca53ec070637ccba9b9a5 \
    https://github.com/aws/aws-lambda-runtime-interface-emulator/releases/download/v1.37/aws-lambda-rie-x86_64 \
    /usr/local/bin/aws-lambda-rie
ENTRYPOINT ["/usr/local/bin/aws-lambda-rie"]
