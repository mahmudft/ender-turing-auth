#!/usr/bin/env bash
# Removes everything deploy.sh created (instance, security group, IAM role).
set -euo pipefail

NAME="${NAME:-ghost-blog}"
REGION="${AWS_REGION:-$(aws configure get region || true)}"
[[ -n "$REGION" ]] || { echo "set AWS_REGION" >&2; exit 1; }
export AWS_REGION="$REGION"

IDS=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=$NAME" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
  --query 'Reservations[].Instances[].InstanceId' --output text)
if [[ -n "$IDS" ]]; then
  echo "==> Terminating $IDS"
  # shellcheck disable=SC2086 # several ids are passed as separate arguments
  aws ec2 terminate-instances --instance-ids $IDS >/dev/null
  # shellcheck disable=SC2086
  aws ec2 wait instance-terminated --instance-ids $IDS
fi

SG_ID=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=$NAME" \
  --query 'SecurityGroups[0].GroupId' --output text)
if [[ "$SG_ID" != "None" ]]; then
  echo "==> Deleting security group $SG_ID"
  aws ec2 delete-security-group --group-id "$SG_ID"
fi

ROLE="$NAME-ssm"
if aws iam get-instance-profile --instance-profile-name "$ROLE" >/dev/null 2>&1; then
  aws iam remove-role-from-instance-profile --instance-profile-name "$ROLE" --role-name "$ROLE" || true
  aws iam delete-instance-profile --instance-profile-name "$ROLE"
fi
if aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  aws iam detach-role-policy --role-name "$ROLE" \
    --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore || true
  aws iam delete-role --role-name "$ROLE"
fi
echo "==> Done"
