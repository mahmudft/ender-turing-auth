#!/usr/bin/env bash
# One-click Ghost deployment on AWS EC2 with no public SSH.
#
#   ./deploy.sh                 # quick tunnel, random https://*.trycloudflare.com URL
#   CF_TUNNEL_TOKEN=... GHOST_URL=https://blog.example.com ./deploy.sh
#                               # named Cloudflare Tunnel on your own hostname
#
# Requires: aws CLI v2 with credentials, jq. Safe to re-run: existing
# resources are reused and a running instance only has its URL printed.
set -euo pipefail

NAME="${NAME:-ghost-blog}"
INSTANCE_TYPE="${INSTANCE_TYPE:-t3.small}"
CF_TUNNEL_TOKEN="${CF_TUNNEL_TOKEN:-}"
GHOST_URL="${GHOST_URL:-}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { printf '==> %s\n' "$*" >&2; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

command -v aws >/dev/null || die "aws CLI not found"
command -v jq >/dev/null || die "jq not found"
if [[ -n "$CF_TUNNEL_TOKEN" && -z "$GHOST_URL" ]]; then
  die "GHOST_URL (e.g. https://blog.example.com) is required with CF_TUNNEL_TOKEN"
fi
aws sts get-caller-identity >/dev/null || die "aws credentials are not configured"
REGION="${AWS_REGION:-$(aws configure get region || true)}"
[[ -n "$REGION" ]] || die "set AWS_REGION"
export AWS_REGION="$REGION"
log "Region: $REGION, name: $NAME"

running_instance() {
  aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=$NAME" "Name=instance-state-name,Values=pending,running" \
    --query 'Reservations[].Instances[].InstanceId' --output text
}

# --- IAM role: lets us reach the VM through SSM Session Manager instead of SSH
ROLE="$NAME-ssm"
if ! aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  log "Creating IAM role $ROLE"
  aws iam create-role --role-name "$ROLE" --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"}, "Action": "sts:AssumeRole"}]
  }' >/dev/null
  aws iam attach-role-policy --role-name "$ROLE" \
    --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
fi
if ! aws iam get-instance-profile --instance-profile-name "$ROLE" >/dev/null 2>&1; then
  aws iam create-instance-profile --instance-profile-name "$ROLE" >/dev/null
  aws iam add-role-to-instance-profile --instance-profile-name "$ROLE" --role-name "$ROLE"
  sleep 10  # new instance profiles take a moment to become usable
fi

# --- Security group with no inbound rules at all (egress only)
VPC_ID=$(aws ec2 describe-vpcs --filters Name=is-default,Values=true \
  --query 'Vpcs[0].VpcId' --output text)
[[ "$VPC_ID" != "None" ]] || die "no default VPC in $REGION"
SG_ID=$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=$NAME" "Name=vpc-id,Values=$VPC_ID" \
  --query 'SecurityGroups[0].GroupId' --output text)
if [[ "$SG_ID" == "None" ]]; then
  log "Creating security group $NAME (no inbound rules)"
  SG_ID=$(aws ec2 create-security-group --group-name "$NAME" --vpc-id "$VPC_ID" \
    --description "Ghost via Cloudflare Tunnel - no inbound" --query GroupId --output text)
fi
INGRESS=$(aws ec2 describe-security-groups --group-ids "$SG_ID" \
  --query 'length(SecurityGroups[0].IpPermissions)' --output text)
[[ "$INGRESS" == "0" ]] || die "security group $SG_ID has inbound rules; refusing to continue"

# --- Instance
INSTANCE_ID=$(running_instance)
if [[ -z "$INSTANCE_ID" ]]; then
  AMI=$(aws ssm get-parameter \
    --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id \
    --query Parameter.Value --output text)
  USER_DATA=$(mktemp)
  trap 'rm -f "$USER_DATA"' EXIT
  sed -e "s|__CF_TUNNEL_TOKEN__|${CF_TUNNEL_TOKEN}|" -e "s|__GHOST_URL__|${GHOST_URL}|" \
    "$HERE/user-data.sh" > "$USER_DATA"

  log "Launching $INSTANCE_TYPE from $AMI (no key pair, no inbound ports)"
  INSTANCE_ID=$(aws ec2 run-instances \
    --image-id "$AMI" --instance-type "$INSTANCE_TYPE" \
    --security-group-ids "$SG_ID" \
    --iam-instance-profile "Name=$ROLE" \
    --metadata-options HttpTokens=required,HttpEndpoint=enabled \
    --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=20,VolumeType=gp3,Encrypted=true}' \
    --user-data "file://$USER_DATA" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME}]" \
    --query 'Instances[0].InstanceId' --output text)
  aws ec2 wait instance-running --instance-ids "$INSTANCE_ID"
else
  log "Reusing running instance $INSTANCE_ID"
fi

# --- Wait for Ghost and read its URL through SSM (no SSH involved)
log "Waiting for Ghost to come up (usually 3-6 minutes)"
URL=""
for _ in $(seq 1 60); do
  CMD_ID=$(aws ssm send-command --instance-ids "$INSTANCE_ID" \
    --document-name AWS-RunShellScript \
    --parameters 'commands=["cat /opt/ghost/url 2>/dev/null || true"]' \
    --query Command.CommandId --output text 2>/dev/null || true)
  if [[ -n "$CMD_ID" ]]; then
    sleep 5
    URL=$(aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" \
      --query StandardOutputContent --output text 2>/dev/null | tr -d '[:space:]' || true)
  fi
  if [[ "$URL" == https://* ]] && curl -fsS -o /dev/null --max-time 10 "$URL"; then
    break
  fi
  URL=""
  sleep 10
done
[[ -n "$URL" ]] || die "Ghost did not become reachable; inspect with: aws ssm start-session --target $INSTANCE_ID (log: /var/log/ghost-setup.log)"

cat <<EOF

Ghost is up.
  Site:   $URL
  Admin:  $URL/ghost   (create the owner account here first)
  Shell:  aws ssm start-session --target $INSTANCE_ID --region $REGION
  Remove: NAME=$NAME $HERE/destroy.sh
EOF
