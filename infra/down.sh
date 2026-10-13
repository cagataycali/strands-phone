#!/usr/bin/env bash
# Delete everything infra/up.sh made (the number is released back to the pool).
set -euo pipefail
cd "$(dirname "$0")/.."
. ./.state.env
read -r -p "Delete $NUMBER, Voice Connector $VC_ID, $INSTANCE_ID, $PUBLIC_IP, $SG_ID and role ${NAME:-strands-phone}-ec2? [y/N] " ok
[ "$ok" = y ] || exit 1
A="--region $REGION"
aws chime-sdk-voice disassociate-phone-numbers-from-voice-connector $A --voice-connector-id $VC_ID --e164-phone-numbers $NUMBER >/dev/null || true
aws chime-sdk-voice delete-phone-number $A --phone-number-id $NUMBER || true
aws chime-sdk-voice delete-voice-connector-origination $A --voice-connector-id $VC_ID || true
aws chime-sdk-voice delete-voice-connector-termination $A --voice-connector-id $VC_ID || true
aws chime-sdk-voice delete-voice-connector $A --voice-connector-id $VC_ID || true
aws ec2 terminate-instances $A --instance-ids $INSTANCE_ID >/dev/null && aws ec2 wait instance-terminated $A --instance-ids $INSTANCE_ID
aws ec2 release-address $A --allocation-id $ALLOC_ID || true
aws ec2 delete-security-group $A --group-id $SG_ID || true
aws iam remove-role-from-instance-profile --instance-profile-name ${NAME:-strands-phone}-ec2 --role-name ${NAME:-strands-phone}-ec2 || true
aws iam delete-instance-profile --instance-profile-name ${NAME:-strands-phone}-ec2 || true
aws iam delete-role-policy --role-name ${NAME:-strands-phone}-ec2 --policy-name nova-sonic-bidi || true
aws iam delete-role --role-name ${NAME:-strands-phone}-ec2 || true
rm -f .state.env
echo down
