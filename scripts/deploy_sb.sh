#!/usr/bin/env bash
set -euo pipefail

TARGET_ORG="${1:-fullsb}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

scripts/gen_flows.sh

SUBFLOWS=(
  "force-app/main/default/flows/SUB_Quote_Main_Automation_TV.flow-meta.xml"
  "force-app/main/default/flows/SUB_QuoteLineItem_Main_Automation_TV.flow-meta.xml"
  "force-app/main/default/flows/SUB_Order_Main_Automation_TV.flow-meta.xml"
  "force-app/main/default/flows/SUB_OrderItem_Main_Automation_TV.flow-meta.xml"
  "force-app/main/default/flows/SUB_Contract_Main_Automation_TV.flow-meta.xml"
  "force-app/main/default/flows/SUB_Asset_Main_Automation_TV.flow-meta.xml"
  "force-app/main/default/flows/SUB_Evaluate_Automation_Context_TV.flow-meta.xml"
  "force-app/main/default/flows/SUB_Log_Automation_Event_TV.flow-meta.xml"
)

RTFS=(
  "force-app/main/default/flows/RTF_Quote_AfterSave_TV.flow-meta.xml"
  "force-app/main/default/flows/RTF_QuoteLineItem_AfterSave_TV.flow-meta.xml"
  "force-app/main/default/flows/RTF_Order_AfterSave_TV.flow-meta.xml"
  "force-app/main/default/flows/RTF_OrderItem_AfterSave_TV.flow-meta.xml"
  "force-app/main/default/flows/RTF_Contract_AfterSave_TV.flow-meta.xml"
  "force-app/main/default/flows/RTF_Asset_AfterSave_TV.flow-meta.xml"
)

echo "Deploying subflows to ${TARGET_ORG}..."
subflow_args=()
for path in "${SUBFLOWS[@]}"; do
  subflow_args+=(--source-dir "$path")
done
sf project deploy start -o "$TARGET_ORG" "${subflow_args[@]}"

echo "Deploying router record-triggered flows to ${TARGET_ORG}..."
rtf_args=()
for path in "${RTFS[@]}"; do
  rtf_args+=(--source-dir "$path")
done
sf project deploy start -o "$TARGET_ORG" "${rtf_args[@]}"

echo "Deployment steps completed."
