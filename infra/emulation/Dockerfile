# Adds the AWS Lambda Runtime Interface Emulator to an image built exactly as scripts/deploy.sh
# builds it; nothing else changes. The emulator comes from AWS's own Lambda base image, pinned.
#   docker build --build-arg BASE=secondchance-lambda:worker -t secondchance-lambda-emulator:worker infra/emulation
ARG BASE
FROM public.ecr.aws/lambda/python:3.12.2026.09.30.01-x86_64@sha256:3d25d4183365989c2f37d625f11c3eaebeb2eb673d3708776731554eec899da6 AS rie

FROM ${BASE}
COPY --from=rie /usr/local/bin/aws-lambda-rie /usr/local/bin/aws-lambda-rie
ENTRYPOINT ["/usr/local/bin/aws-lambda-rie"]
