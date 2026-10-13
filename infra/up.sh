#!/usr/bin/env bash
# Provision everything strands-phone needs, idempotently, and write .state.env.
#   infra/up.sh [--state NJ] [--region us-east-1] [--name strands-phone]
# Creates (all named/tagged --name): a Chime SDK number + Voice Connector (termination
# from the host, origination to the host), an EC2 t4g.small + Elastic IP, a security group (ssh from
# you; SIP/RTP from Chime only), and an instance role that can call only Nova Sonic. Costs money while idle.
set -euo pipefail
cd "$(dirname "$0")/.."
NAME=strands-phone REGION=us-east-1 STATE=NJ
while [ $# -gt 0 ]; do case $1 in --state) STATE=$2; shift 2;; --name) NAME=$2; shift 2;; --region) REGION=$2; shift 2;; *) echo "unknown $1"; exit 2;; esac; done
[ -f .state.env ] && . ./.state.env  # a saved NAME wins, so an existing deployment keeps its names
A="--region $REGION --output text"
CHIME_CIDRS="3.80.16.0/23 52.55.62.128/25 52.55.63.0/25 34.212.95.128/25 34.223.21.0/25 99.77.253.0/24 99.77.254.0/24"
KEY=${KEY:-$HOME/.ssh/$NAME.pem}

# --- IAM: instance role, Nova Sonic only. The stream authorises against bedrock:InvokeModel (measured).
if ! aws iam get-role --role-name $NAME-ec2 >/dev/null 2>&1; then
  aws iam create-role --role-name $NAME-ec2 --assume-role-policy-document \
    '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
  aws iam create-instance-profile --instance-profile-name $NAME-ec2 >/dev/null
  aws iam add-role-to-instance-profile --instance-profile-name $NAME-ec2 --role-name $NAME-ec2
  sleep 10
fi
aws iam put-role-policy --role-name $NAME-ec2 --policy-name nova-sonic-bidi --policy-document \
  '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["bedrock:InvokeModel","bedrock:InvokeModelWithBidirectionalStream"],"Resource":["arn:aws:bedrock:*::foundation-model/amazon.nova-2-sonic-v1:0","arn:aws:bedrock:*::foundation-model/amazon.nova-sonic-v1:0"]}]}'

# --- network + host
VPC=$(aws ec2 describe-vpcs $A --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId')
SG_ID=${SG_ID:-$(aws ec2 describe-security-groups $A --filters Name=group-name,Values=$NAME --query 'SecurityGroups[0].GroupId' 2>/dev/null || true)}
if [ -z "$SG_ID" ] || [ "$SG_ID" = None ]; then
  SG_ID=$(aws ec2 create-security-group $A --group-name $NAME --description "SIP/RTP from Chime Voice Connector, ssh from operator" --vpc-id $VPC --query GroupId)
  for c in $CHIME_CIDRS; do
    aws ec2 authorize-security-group-ingress --region $REGION --group-id $SG_ID --ip-permissions \
      "IpProtocol=udp,FromPort=5060,ToPort=5060,IpRanges=[{CidrIp=$c}]" "IpProtocol=udp,FromPort=10000,ToPort=20000,IpRanges=[{CidrIp=$c}]" >/dev/null
  done
fi
MYIP=$(curl -s https://checkip.amazonaws.com)
aws ec2 authorize-security-group-ingress --region $REGION --group-id $SG_ID --protocol tcp --port 22 --cidr $MYIP/32 >/dev/null 2>&1 || true
[ -f "$KEY" ] || { aws ec2 create-key-pair $A --key-name $NAME --query KeyMaterial > "$KEY"; chmod 600 "$KEY"; }
INSTANCE_ID=${INSTANCE_ID:-$(aws ec2 describe-instances $A --filters Name=tag:Name,Values=$NAME Name=instance-state-name,Values=running,stopped --query 'Reservations[0].Instances[0].InstanceId' || true)}
if [ -z "$INSTANCE_ID" ] || [ "$INSTANCE_ID" = None ]; then
  AMI=$(aws ssm get-parameter $A --name /aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id --query Parameter.Value)
  INSTANCE_ID=$(aws ec2 run-instances $A --image-id $AMI --instance-type t4g.small --key-name $NAME --security-group-ids $SG_ID \
    --iam-instance-profile Name=$NAME-ec2 --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME}]" --query 'Instances[0].InstanceId')
  aws ec2 wait instance-running --region $REGION --instance-ids $INSTANCE_ID
fi
aws ec2 describe-iam-instance-profile-associations $A --filters Name=instance-id,Values=$INSTANCE_ID --query 'IamInstanceProfileAssociations[0].AssociationId' | grep -q iip- \
  || aws ec2 associate-iam-instance-profile --region $REGION --instance-id $INSTANCE_ID --iam-instance-profile Name=$NAME-ec2 >/dev/null
if [ -z "${ALLOC_ID:-}" ]; then
  read -r ALLOC_ID PUBLIC_IP < <(aws ec2 allocate-address $A --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=$NAME}]" --query '[AllocationId,PublicIp]')
fi
aws ec2 associate-address --region $REGION --instance-id $INSTANCE_ID --allocation-id $ALLOC_ID >/dev/null

# --- telephony
VC_ID=${VC_ID:-$(aws chime-sdk-voice list-voice-connectors $A --query "VoiceConnectors[?Name=='$NAME'].VoiceConnectorId | [0]")}
if [ -z "$VC_ID" ] || [ "$VC_ID" = None ]; then
  VC_ID=$(aws chime-sdk-voice create-voice-connector $A --name $NAME --aws-region $REGION --no-require-encryption --query VoiceConnector.VoiceConnectorId)
fi
VC_HOST=$(aws chime-sdk-voice get-voice-connector $A --voice-connector-id $VC_ID --query VoiceConnector.OutboundHostName)
if [ -z "${NUMBER:-}" ]; then
  NUMBER=$(aws chime-sdk-voice search-available-phone-numbers $A --country US --phone-number-type Local --state $STATE --max-results 1 --query 'E164PhoneNumbers[0]')
  ORDER=$(aws chime-sdk-voice create-phone-number-order $A --product-type VoiceConnector --e164-phone-numbers $NUMBER --query PhoneNumberOrder.PhoneNumberOrderId)
  until [ "$(aws chime-sdk-voice get-phone-number-order $A --phone-number-order-id $ORDER --query PhoneNumberOrder.Status)" = Successful ]; do sleep 5; done
fi
aws chime-sdk-voice associate-phone-numbers-with-voice-connector --region $REGION --voice-connector-id $VC_ID --e164-phone-numbers $NUMBER --force-associate >/dev/null
aws chime-sdk-voice put-voice-connector-termination --region $REGION --voice-connector-id $VC_ID --termination \
  "{\"CpsLimit\":1,\"DefaultPhoneNumber\":\"$NUMBER\",\"CallingRegions\":[\"US\"],\"CidrAllowedList\":[\"$PUBLIC_IP/32\"],\"Disabled\":false}" >/dev/null
aws chime-sdk-voice put-voice-connector-origination --region $REGION --voice-connector-id $VC_ID --origination \
  "{\"Routes\":[{\"Host\":\"$PUBLIC_IP\",\"Port\":5060,\"Protocol\":\"UDP\",\"Priority\":1,\"Weight\":1}],\"Disabled\":false}" >/dev/null

cat > .state.env <<S
NAME=$NAME
REGION=$REGION
NUMBER=$NUMBER
VC_ID=$VC_ID
VC_HOST=$VC_HOST
INSTANCE_ID=$INSTANCE_ID
ALLOC_ID=$ALLOC_ID
PUBLIC_IP=$PUBLIC_IP
SG_ID=$SG_ID
KEY=$KEY
SIP_ALLOW=$(echo $CHIME_CIDRS | tr " " ",")
S
echo "up: $NUMBER -> $VC_HOST -> $PUBLIC_IP ($INSTANCE_ID). Next: deploy/deploy.sh"
