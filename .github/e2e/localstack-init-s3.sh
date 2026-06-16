#!/bin/bash
# DISTR-762 — LocalStack ready-hook: create the customer S3 bucket.
# Runs once LocalStack's S3 service is ready (mounted into
# /etc/localstack/init/ready.d/). The compose healthcheck greps for this
# bucket, so atlan-app only starts after the bucket exists.
set -euo pipefail
awslocal s3 mb s3://atlan-customer-e2e
echo "DISTR-762: created s3://atlan-customer-e2e"
