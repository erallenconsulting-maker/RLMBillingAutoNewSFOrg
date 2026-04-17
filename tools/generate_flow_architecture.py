#!/usr/bin/env python3
"""Generate Salesforce Flow metadata routers + main subflows from CSV specs."""

from __future__ import annotations

import csv
import os
from pathlib import Path
import xml.etree.ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "config" / "flow_objects.yml"
FLOWS_DIR = REPO_ROOT / "force-app" / "main" / "default" / "flows"

NS = "http://soap.sforce.com/2006/04/metadata"
ET.register_namespace("", NS)


def qname(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def add(parent: ET.Element, tag: str, text: str | None = None) -> ET.Element:
    el = ET.SubElement(parent, qname(tag))
    if text is not None:
        el.text = text
    return el


def add_value(parent: ET.Element, *, string: str | None = None, boolean: bool | None = None, element_ref: str | None = None) -> ET.Element:
    value = add(parent, "value")
    if string is not None:
        add(value, "stringValue", string)
    elif boolean is not None:
        add(value, "booleanValue", "true" if boolean else "false")
    elif element_ref is not None:
        add(value, "elementReference", element_ref)
    return value


def parse_simple_yaml(path: Path) -> list[dict[str, str]]:
    objects: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == "objects:":
            continue
        if stripped.startswith("- "):
            if current:
                objects.append(current)
            current = {}
            stripped = stripped[2:].strip()
            if stripped:
                key, value = [part.strip() for part in stripped.split(":", 1)]
                current[key] = value.strip('"\'')
            continue
        if current is None or ":" not in stripped:
            continue
        key, value = [part.strip() for part in stripped.split(":", 1)]
        current[key] = value.strip('"\'')
    if current:
        objects.append(current)
    return objects


def load_csv_summary(csv_path: Path, object_api: str) -> tuple[int, list[str]]:
    rows = 0
    field_names: list[str] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        object_key = "Object/Custom Metadata Type Field API Name is Located On"
        field_key = "Field API Name"
        for row in reader:
            if (row.get(object_key) or "").strip() != object_api:
                continue
            rows += 1
            field_api = (row.get(field_key) or "").strip()
            if field_api and field_api not in field_names:
                field_names.append(field_api)
    return rows, field_names[:5]


def add_common_flow_metadata(root: ET.Element) -> None:
    add(root, "apiVersion", "66.0")
    add(root, "environments", "Default")
    for name, value in (
        ("BuilderType", "LightningFlowBuilder"),
        ("CanvasMode", "AUTO_LAYOUT_CANVAS"),
        ("OriginBuilderType", "LightningFlowBuilder"),
    ):
        pmv = add(root, "processMetadataValues")
        add(pmv, "name", name)
        value_el = add(pmv, "value")
        add(value_el, "stringValue", value)
    add(root, "processType", "AutoLaunchedFlow")


def add_log_subflow(parent: ET.Element, *, name: str, label: str, action: str, message_element_reference: str | None, message_string: str | None, flow_api_name: str, object_api: str, record_reference: str, correlation_reference: str, required_level: str, connector_target: str | None = None) -> None:
    subflow = add(parent, "subflows")
    add(subflow, "name", name)
    add(subflow, "label", label)
    add(subflow, "locationX", "0")
    add(subflow, "locationY", "0")
    if connector_target:
        connector = add(subflow, "connector")
        add(connector, "targetReference", connector_target)
    add(subflow, "flowName", "SUB_Log_Automation_Event_TV")

    for param_name, value_type, value in (
        ("inAction", "string", action),
        ("inCorrelationId", "element", correlation_reference),
        ("inFlowApiName", "string", flow_api_name),
        ("inObjectApiName", "string", object_api),
        ("inRecordId", "element", record_reference),
        ("inRequiredLogLevel", "string", required_level),
    ):
        input_assignment = add(subflow, "inputAssignments")
        add(input_assignment, "name", param_name)
        if value_type == "string":
            add_value(input_assignment, string=value)
        else:
            add_value(input_assignment, element_ref=value)

    msg_assignment = add(subflow, "inputAssignments")
    add(msg_assignment, "name", "inMessage")
    if message_element_reference:
        add_value(msg_assignment, element_ref=message_element_reference)
    else:
        add_value(msg_assignment, string=message_string or "")


def generate_router_flow(config: dict[str, str]) -> ET.Element:
    object_api = config["object_api"]
    flow_api = f"RTF_{object_api}_AfterSave_TV"

    root = ET.Element(qname("Flow"))
    add_common_flow_metadata(root)
    add(root, "description", f"Router flow generated from {Path(config['csv_spec']).name}. Uses SUB_Evaluate_Automation_Context_TV and calls {config['main_subflow_api']} when context allows.")
    add(root, "interviewLabel", f"{flow_api} {{!$Flow.CurrentDateTime}}")
    add(root, "label", flow_api.replace("_", " "))

    should_run = add(root, "decisions")
    add(should_run, "name", "Should_Run_Context")
    add(should_run, "label", "Should Run Context")
    add(should_run, "locationX", "0")
    add(should_run, "locationY", "0")
    default_connector = add(should_run, "defaultConnector")
    add(default_connector, "targetReference", "Log_Skipped")
    add(should_run, "defaultConnectorLabel", "No")

    rule = add(should_run, "rules")
    add(rule, "name", "Yes")
    add(rule, "conditionLogic", "and")
    cond = add(rule, "conditions")
    add(cond, "leftValueReference", "varShouldRun")
    add(cond, "operator", "EqualTo")
    right_value = add(cond, "rightValue")
    add(right_value, "booleanValue", "true")
    rule_connector = add(rule, "connector")
    add(rule_connector, "targetReference", "Call_Main_Automation")
    add(rule, "label", "Yes")

    eval_context = add(root, "subflows")
    add(eval_context, "name", "Eval_Context")
    add(eval_context, "label", "Evaluate Automation Context")
    add(eval_context, "locationX", "0")
    add(eval_context, "locationY", "0")
    eval_connector = add(eval_context, "connector")
    add(eval_connector, "targetReference", "Should_Run_Context")
    add(eval_context, "flowName", "SUB_Evaluate_Automation_Context_TV")

    for input_name, value_type, value in (
        ("inObjectApiName", "string", object_api),
        ("inIsHardwareContext", "element", f"$Record.{config['hardware_context_field']}"),
        ("inRecordIdForLog", "element", "$Record.Id"),
    ):
        assignment = add(eval_context, "inputAssignments")
        add(assignment, "name", input_name)
        if value_type == "string":
            add_value(assignment, string=value)
        else:
            add_value(assignment, element_ref=value)

    for output_name, assign_to in (
        ("outShouldRun", "varShouldRun"),
        ("outStopReason", "varStopReason"),
        ("outCorrelationId", "varCorrelationId"),
    ):
        output = add(eval_context, "outputAssignments")
        add(output, "assignToReference", assign_to)
        add(output, "name", output_name)

    call_main = add(root, "subflows")
    add(call_main, "name", "Call_Main_Automation")
    add(call_main, "label", "Call Main Automation")
    add(call_main, "locationX", "0")
    add(call_main, "locationY", "0")
    call_main_connector = add(call_main, "connector")
    add(call_main_connector, "targetReference", "Log_Main_Invoked")
    add(call_main, "flowName", config["main_subflow_api"])

    for input_name, value_type, value in (
        ("inRecordId", "element", "$Record.Id"),
        ("inCorrelationId", "element", "varCorrelationId"),
    ):
        assignment = add(call_main, "inputAssignments")
        add(assignment, "name", input_name)
        if value_type == "string":
            add_value(assignment, string=value)
        else:
            add_value(assignment, element_ref=value)

    add_log_subflow(
        root,
        name="Log_Main_Invoked",
        label="Log Main Invoked",
        action="RUN_MAIN",
        message_element_reference=None,
        message_string=f"Main automation subflow {config['main_subflow_api']} invoked.",
        flow_api_name=flow_api,
        object_api=object_api,
        record_reference="$Record.Id",
        correlation_reference="varCorrelationId",
        required_level="INFO",
    )

    add_log_subflow(
        root,
        name="Log_Skipped",
        label="Log Skipped",
        action="SKIP",
        message_element_reference="varStopReason",
        message_string=None,
        flow_api_name=flow_api,
        object_api=object_api,
        record_reference="$Record.Id",
        correlation_reference="varCorrelationId",
        required_level="INFO",
    )

    start = add(root, "start")
    add(start, "locationX", "0")
    add(start, "locationY", "0")
    start_connector = add(start, "connector")
    add(start_connector, "targetReference", "Eval_Context")
    add(start, "filterLogic", "1")
    start_filter = add(start, "filters")
    add(start_filter, "field", "Id")
    add(start_filter, "operator", "IsNull")
    add_value(start_filter, boolean=False)
    add(start, "object", object_api)
    add(start, "recordTriggerType", "CreateAndUpdate")
    add(start, "triggerType", "RecordAfterSave")

    add(root, "status", "Draft")

    for name, data_type in (
        ("varCorrelationId", "String"),
        ("varShouldRun", "Boolean"),
        ("varStopReason", "String"),
    ):
        variable = add(root, "variables")
        add(variable, "name", name)
        add(variable, "dataType", data_type)
        add(variable, "isCollection", "false")
        add(variable, "isInput", "false")
        add(variable, "isOutput", "false")

    return root


def generate_main_subflow(config: dict[str, str], summary_rows: int, field_samples: list[str]) -> ET.Element:
    object_api = config["object_api"]
    flow_api = config["main_subflow_api"]
    sample_text = ", ".join(field_samples) if field_samples else "No field rows found in CSV"

    root = ET.Element(qname("Flow"))
    add_common_flow_metadata(root)
    add(root, "description", f"Main automation subflow generated from {Path(config['csv_spec']).name}. CSV rows for {object_api}: {summary_rows}. Field samples: {sample_text}.")
    add(root, "interviewLabel", f"{flow_api} {{!$Flow.CurrentDateTime}}")
    add(root, "label", flow_api.replace("_", " "))

    record_lookup = add(root, "recordLookups")
    add(record_lookup, "name", "Get_Triggering_Record")
    add(record_lookup, "label", "Get Triggering Record")
    add(record_lookup, "locationX", "0")
    add(record_lookup, "locationY", "0")
    add(record_lookup, "assignNullValuesIfNoRecordsFound", "false")
    lookup_connector = add(record_lookup, "connector")
    add(lookup_connector, "targetReference", "Set_Run_Summary")
    add(record_lookup, "filterLogic", "and")
    lookup_filter = add(record_lookup, "filters")
    add(lookup_filter, "field", "Id")
    add(lookup_filter, "operator", "EqualTo")
    add_value(lookup_filter, element_ref="inRecordId")
    add(record_lookup, "getFirstRecordOnly", "true")
    add(record_lookup, "object", object_api)
    add(record_lookup, "storeOutputAutomatically", "true")

    summary_assignment = add(root, "assignments")
    add(summary_assignment, "name", "Set_Run_Summary")
    add(summary_assignment, "label", "Set Run Summary")
    add(summary_assignment, "locationX", "0")
    add(summary_assignment, "locationY", "0")
    item = add(summary_assignment, "assignmentItems")
    add(item, "assignToReference", "outRunSummary")
    add(item, "operator", "Assign")
    add_value(item, string=f"CSV rows={summary_rows}; objectToggle={config['object_disable_toggle_field']}; hardwareToggle={config['hardware_disable_toggle_field']}")
    summary_connector = add(summary_assignment, "connector")
    add(summary_connector, "targetReference", "Log_Main_Subflow_Execution")

    add_log_subflow(
        root,
        name="Log_Main_Subflow_Execution",
        label="Log Main Subflow Execution",
        action="MAIN_SUBFLOW",
        message_element_reference="outRunSummary",
        message_string=None,
        flow_api_name=flow_api,
        object_api=object_api,
        record_reference="inRecordId",
        correlation_reference="inCorrelationId",
        required_level="INFO",
    )

    start = add(root, "start")
    add(start, "locationX", "0")
    add(start, "locationY", "0")
    start_connector = add(start, "connector")
    add(start_connector, "targetReference", "Get_Triggering_Record")

    add(root, "status", "Draft")

    in_record = add(root, "variables")
    add(in_record, "name", "inRecordId")
    add(in_record, "dataType", "String")
    add(in_record, "isCollection", "false")
    add(in_record, "isInput", "true")
    add(in_record, "isOutput", "false")

    in_correlation = add(root, "variables")
    add(in_correlation, "name", "inCorrelationId")
    add(in_correlation, "dataType", "String")
    add(in_correlation, "isCollection", "false")
    add(in_correlation, "isInput", "true")
    add(in_correlation, "isOutput", "false")

    out_summary = add(root, "variables")
    add(out_summary, "name", "outRunSummary")
    add(out_summary, "dataType", "String")
    add(out_summary, "isCollection", "false")
    add(out_summary, "isInput", "false")
    add(out_summary, "isOutput", "true")

    return root


def write_flow(path: Path, root: ET.Element) -> None:
    ET.indent(root, space="    ")
    tree = ET.ElementTree(root)
    tree.write(path, encoding="UTF-8", xml_declaration=True)


def main() -> None:
    configs = parse_simple_yaml(CONFIG_PATH)
    if not configs:
        raise SystemExit(f"No objects configured in {CONFIG_PATH}")

    FLOWS_DIR.mkdir(parents=True, exist_ok=True)

    for config in configs:
        csv_path = REPO_ROOT / config["csv_spec"]
        summary_rows, field_samples = load_csv_summary(csv_path, config["object_api"])

        router_api = f"RTF_{config['object_api']}_AfterSave_TV"
        router_path = FLOWS_DIR / f"{router_api}.flow-meta.xml"
        write_flow(router_path, generate_router_flow(config))

        main_path = FLOWS_DIR / f"{config['main_subflow_api']}.flow-meta.xml"
        write_flow(main_path, generate_main_subflow(config, summary_rows, field_samples))

        print(f"Generated: {router_path.relative_to(REPO_ROOT)}")
        print(f"Generated: {main_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
