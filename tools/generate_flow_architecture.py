#!/usr/bin/env python3
"""Generate Salesforce Flow metadata routers + main subflows from CSV specs.

Main subflows emit per-object field-update nodes derived from the CSV mappings:
- recordLookups for each required parent record
- recordUpdates grouped by trigger type (create-only, update-only, always)
- decisions element to branch create vs. update paths when both exist

Router flows pass inIsNewRecord (Boolean) to the main subflow so it can
gate create-only vs update-only field assignments.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field as dc_field
from pathlib import Path
import xml.etree.ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "config" / "flow_objects.yml"
FLOWS_DIR = REPO_ROOT / "force-app" / "main" / "default" / "flows"

NS = "http://soap.sforce.com/2006/04/metadata"
ET.register_namespace("", NS)

# Trigger category constants matching CSV "Behavior Needs to Occur When?" values
TRIGGER_CREATE = "Record Creation Only"
TRIGGER_UPDATE = "Record Update Only"
TRIGGER_BOTH = "Record Creation or Record Update"

API_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(__c)?$")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class FieldMapping:
    """One CSV row parsed into a structured mapping."""
    target_field: str
    data_type: str
    trigger: str           # TRIGGER_CREATE / TRIGGER_UPDATE / TRIGGER_BOTH / ""
    source_parent: str     # source object API name; "" if no resolvable source
    source_field: str      # source field API name; "" if no resolvable source
    behavior_note: str     # truncated human description for novice admins


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def qname(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def add(parent: ET.Element, tag: str, text: str | None = None) -> ET.Element:
    el = ET.SubElement(parent, qname(tag))
    if text is not None:
        el.text = text
    return el


def add_value(
    parent: ET.Element,
    *,
    string: str | None = None,
    boolean: bool | None = None,
    element_ref: str | None = None,
) -> ET.Element:
    value = add(parent, "value")
    if string is not None:
        add(value, "stringValue", string)
    elif boolean is not None:
        add(value, "booleanValue", "true" if boolean else "false")
    elif element_ref is not None:
        add(value, "elementReference", element_ref)
    return value


def is_valid_api_name(name: str) -> bool:
    return bool(API_NAME_RE.match((name or "").strip()))


def parse_source_ref(src_api_val: str) -> tuple[str, str] | None:
    """Parse 'ObjectApi.FieldApi' from the source API column.

    Returns (source_object_api, source_field_api) or None if unparseable.
    Rejects values whose object or field part is not a valid API name.
    """
    val = (src_api_val or "").strip()
    if not val or "." not in val:
        return None
    obj_part, field_part = val.split(".", 1)
    obj_part = obj_part.strip()
    field_part = field_part.strip()
    if not is_valid_api_name(obj_part) or not is_valid_api_name(field_part):
        return None
    return (obj_part, field_part)


def parse_parent_lookups(value: str) -> dict[str, str]:
    """Parse 'Object:LookupField,Object:LookupField' into a mapping.

    Returns {parent_object_api: lookup_field_on_triggering_record}.
    """
    result: dict[str, str] = {}
    for pair in (value or "").split(","):
        pair = pair.strip()
        if ":" in pair:
            obj, lookup = pair.split(":", 1)
            result[obj.strip()] = lookup.strip()
    return result


# ---------------------------------------------------------------------------
# CSV loading
# ---------------------------------------------------------------------------

def load_csv_field_mappings(csv_path: Path, object_api: str) -> list[FieldMapping]:
    """Return structured FieldMapping objects for the given object from the CSV."""
    mappings: list[FieldMapping] = []
    seen_targets: set[str] = set()

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            obj_col = (
                row.get("Object/Custom Metadata Type Field API Name is Located On") or ""
            ).strip()
            if obj_col != object_api:
                continue

            target_field = (row.get("Field API Name") or "").strip()
            if not target_field or target_field in seen_targets:
                continue
            seen_targets.add(target_field)

            data_type = (row.get("Data Type") or "").strip()
            trigger = (row.get("Behavior Needs to Occur When?") or "").strip()
            src_api = (
                row.get(
                    "Should Carry Over Values or Mappings from Object/Metadata Table API Name"
                )
                or ""
            ).strip()
            behavior = (
                (row.get("Expected Automation Behavior") or "")
                .replace("\n", " ")
                .strip()[:150]
            )

            parsed = parse_source_ref(src_api)
            source_parent = parsed[0] if parsed else ""
            source_field = parsed[1] if parsed else ""

            mappings.append(
                FieldMapping(
                    target_field=target_field,
                    data_type=data_type,
                    trigger=trigger,
                    source_parent=source_parent,
                    source_field=source_field,
                    behavior_note=behavior,
                )
            )

    return mappings


# ---------------------------------------------------------------------------
# Flow element builders
# ---------------------------------------------------------------------------

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
        add(add(pmv, "value"), "stringValue", value)
    add(root, "processType", "AutoLaunchedFlow")


def add_record_lookup(
    root: ET.Element,
    *,
    name: str,
    label: str,
    connector_target: str,
    filter_field: str,
    filter_element_ref: str,
    object_api: str,
) -> None:
    rl = add(root, "recordLookups")
    add(rl, "name", name)
    add(rl, "label", label)
    add(rl, "locationX", "0")
    add(rl, "locationY", "0")
    add(rl, "assignNullValuesIfNoRecordsFound", "false")
    conn = add(rl, "connector")
    add(conn, "targetReference", connector_target)
    add(rl, "filterLogic", "and")
    flt = add(rl, "filters")
    add(flt, "field", filter_field)
    add(flt, "operator", "EqualTo")
    add_value(flt, element_ref=filter_element_ref)
    add(rl, "getFirstRecordOnly", "true")
    add(rl, "object", object_api)
    add(rl, "storeOutputAutomatically", "true")


def add_record_update(
    root: ET.Element,
    *,
    name: str,
    label: str,
    connector_target: str | None,
    field_assignments: list[tuple[str, str]],  # [(target_field, element_ref), ...]
    id_element_ref: str,
    object_api: str,
) -> None:
    """Add a recordUpdates element that writes field values to a record by Id.

    Uses filters (Id = id_element_ref) to identify which record to update.
    Element order: name, label, locationX/Y, connector, inputAssignments, filters, object.
    """
    ru = add(root, "recordUpdates")
    add(ru, "name", name)
    add(ru, "label", label)
    add(ru, "locationX", "0")
    add(ru, "locationY", "0")
    if connector_target:
        conn = add(ru, "connector")
        add(conn, "targetReference", connector_target)
    for tgt_field, elem_ref in field_assignments:
        ia = add(ru, "inputAssignments")
        add(ia, "field", tgt_field)
        add_value(ia, element_ref=elem_ref)
    flt = add(ru, "filters")
    add(flt, "field", "Id")
    add(flt, "operator", "EqualTo")
    add_value(flt, element_ref=id_element_ref)
    add(ru, "object", object_api)


def add_log_subflow(
    parent: ET.Element,
    *,
    name: str,
    label: str,
    action: str,
    message_element_reference: str | None,
    message_string: str | None,
    flow_api_name: str,
    object_api: str,
    record_reference: str,
    correlation_reference: str,
    required_level: str,
    connector_target: str | None = None,
) -> None:
    subflow = add(parent, "subflows")
    add(subflow, "name", name)
    add(subflow, "label", label)
    add(subflow, "locationX", "0")
    add(subflow, "locationY", "0")
    if connector_target:
        conn = add(subflow, "connector")
        add(conn, "targetReference", connector_target)
    add(subflow, "flowName", "SUB_Log_Automation_Event_TV")

    for param_name, value_type, value in (
        ("inAction", "string", action),
        ("inCorrelationId", "element", correlation_reference),
        ("inFlowApiName", "string", flow_api_name),
        ("inObjectApiName", "string", object_api),
        ("inRecordId", "element", record_reference),
        ("inRequiredLogLevel", "string", required_level),
    ):
        ia = add(subflow, "inputAssignments")
        add(ia, "name", param_name)
        if value_type == "string":
            add_value(ia, string=value)
        else:
            add_value(ia, element_ref=value)

    msg_ia = add(subflow, "inputAssignments")
    add(msg_ia, "name", "inMessage")
    if message_element_reference:
        add_value(msg_ia, element_ref=message_element_reference)
    else:
        add_value(msg_ia, string=message_string or "")


# ---------------------------------------------------------------------------
# Router flow
# ---------------------------------------------------------------------------

def generate_router_flow(config: dict[str, str]) -> ET.Element:
    object_api = config["object_api"]
    flow_api = f"RTF_{object_api}_AfterSave_TV"

    root = ET.Element(qname("Flow"))
    add_common_flow_metadata(root)
    add(
        root,
        "description",
        f"Router flow for {object_api}. Calls SUB_Evaluate_Automation_Context_TV then "
        f"{config['main_subflow_api']} when context allows. Passes inIsNewRecord so "
        "the main subflow can gate create-only vs update-only field assignments.",
    )
    add(root, "interviewLabel", f"{flow_api} {{!$Flow.CurrentDateTime}}")
    add(root, "label", flow_api.replace("_", " "))

    # Decision: should the main subflow run?
    should_run = add(root, "decisions")
    add(should_run, "name", "Should_Run_Context")
    add(should_run, "label", "Should Run Context")
    add(should_run, "locationX", "0")
    add(should_run, "locationY", "0")
    add(add(should_run, "defaultConnector"), "targetReference", "Log_Skipped")
    add(should_run, "defaultConnectorLabel", "No")
    rule = add(should_run, "rules")
    add(rule, "name", "Yes")
    add(rule, "conditionLogic", "and")
    cond = add(rule, "conditions")
    add(cond, "leftValueReference", "varShouldRun")
    add(cond, "operator", "EqualTo")
    add(add(cond, "rightValue"), "booleanValue", "true")
    add(add(rule, "connector"), "targetReference", "Call_Main_Automation")
    add(rule, "label", "Yes")

    # Formula: is this a record create? ISBLANK($Record__Prior.Id) = true on create
    frm = add(root, "formulas")
    add(frm, "name", "frmIsNewRecord")
    add(frm, "dataType", "Boolean")
    add(frm, "expression", "ISBLANK({!$Record__Prior.Id})")

    # Subflow: evaluate automation context
    eval_ctx = add(root, "subflows")
    add(eval_ctx, "name", "Eval_Context")
    add(eval_ctx, "label", "Evaluate Automation Context")
    add(eval_ctx, "locationX", "0")
    add(eval_ctx, "locationY", "0")
    add(add(eval_ctx, "connector"), "targetReference", "Should_Run_Context")
    add(eval_ctx, "flowName", "SUB_Evaluate_Automation_Context_TV")
    for input_name, value_type, value in (
        ("inObjectApiName", "string", object_api),
        ("inIsHardwareContext", "element", f"$Record.{config['hardware_context_field']}"),
        ("inRecordIdForLog", "element", "$Record.Id"),
    ):
        ia = add(eval_ctx, "inputAssignments")
        add(ia, "name", input_name)
        if value_type == "string":
            add_value(ia, string=value)
        else:
            add_value(ia, element_ref=value)
    for output_name, assign_to in (
        ("outShouldRun", "varShouldRun"),
        ("outStopReason", "varStopReason"),
        ("outCorrelationId", "varCorrelationId"),
    ):
        oa = add(eval_ctx, "outputAssignments")
        add(oa, "assignToReference", assign_to)
        add(oa, "name", output_name)

    # Subflow: call main automation
    call_main = add(root, "subflows")
    add(call_main, "name", "Call_Main_Automation")
    add(call_main, "label", "Call Main Automation")
    add(call_main, "locationX", "0")
    add(call_main, "locationY", "0")
    add(add(call_main, "connector"), "targetReference", "Log_Main_Invoked")
    add(call_main, "flowName", config["main_subflow_api"])
    for input_name, value_type, value in (
        ("inRecordId", "element", "$Record.Id"),
        ("inCorrelationId", "element", "varCorrelationId"),
        ("inIsNewRecord", "element", "frmIsNewRecord"),
    ):
        ia = add(call_main, "inputAssignments")
        add(ia, "name", input_name)
        if value_type == "string":
            add_value(ia, string=value)
        else:
            add_value(ia, element_ref=value)

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

    # Start element (required child order: locationX/Y, connector, filterLogic, filters, object, recordTriggerType, triggerType)
    start = add(root, "start")
    add(start, "locationX", "0")
    add(start, "locationY", "0")
    add(add(start, "connector"), "targetReference", "Eval_Context")
    add(start, "filterLogic", "1")
    flt = add(start, "filters")
    add(flt, "field", "Id")
    add(flt, "operator", "IsNull")
    add_value(flt, boolean=False)
    add(start, "object", object_api)
    add(start, "recordTriggerType", "CreateAndUpdate")
    add(start, "triggerType", "RecordAfterSave")

    add(root, "status", "Draft")

    for var_name, data_type in (
        ("varCorrelationId", "String"),
        ("varShouldRun", "Boolean"),
        ("varStopReason", "String"),
    ):
        var = add(root, "variables")
        add(var, "name", var_name)
        add(var, "dataType", data_type)
        add(var, "isCollection", "false")
        add(var, "isInput", "false")
        add(var, "isOutput", "false")

    return root


# ---------------------------------------------------------------------------
# Main subflow — deep generation from CSV field mappings
# ---------------------------------------------------------------------------

def _source_element_ref(m: FieldMapping, object_api: str) -> str:
    """Return the Flow elementReference string for the source of a FieldMapping."""
    if m.source_parent == object_api:
        return f"Get_Triggering_Record.{m.source_field}"
    return f"Get_{m.source_parent}.{m.source_field}"


def generate_main_subflow(
    config: dict[str, str],
    mappings: list[FieldMapping],
) -> ET.Element:
    """Generate main subflow with deep per-object field update nodes.

    Structure:
      Start
        → Get_Triggering_Record
        → Get_<Parent1> ... Get_<ParentN>
        → Update_Record_Always  (fields with no trigger-type restriction)
        → Decide_Create_Or_Update  (if create-only or update-only fields exist)
            Yes_Create → Update_Record_Create → Log
            No (Update) → Update_Record_Update → Log
        → Log_Main_Subflow_Execution  (terminal)
    """
    object_api = config["object_api"]
    flow_api = config["main_subflow_api"]
    parent_lookup_map = parse_parent_lookups(config.get("parent_lookups", ""))

    # Separate skipped mappings for description
    skipped: list[FieldMapping] = []

    def is_resolvable(m: FieldMapping) -> bool:
        if not m.source_parent or not m.source_field:
            return False
        if m.source_parent == object_api:
            return True
        return m.source_parent in parent_lookup_map

    resolvable = [m for m in mappings if is_resolvable(m)]
    skipped = [m for m in mappings if not is_resolvable(m)]

    always_fields = [m for m in resolvable if m.trigger == TRIGGER_BOTH]
    create_fields = [m for m in resolvable if m.trigger == TRIGGER_CREATE]
    update_fields = [m for m in resolvable if m.trigger == TRIGGER_UPDATE]

    has_always = bool(always_fields)
    has_create = bool(create_fields)
    has_update = bool(update_fields)
    has_conditional = has_create or has_update

    # Unique parent objects we need to look up (in the order they appear in parent_lookup_map)
    all_used_parents: list[str] = []
    for m in always_fields + create_fields + update_fields:
        if m.source_parent != object_api and m.source_parent not in all_used_parents:
            all_used_parents.append(m.source_parent)

    # Summary for description
    total_mapped = len(always_fields) + len(create_fields) + len(update_fields)
    skipped_count = len(skipped)
    skip_summary = (
        f"{skipped_count} field(s) skipped (no resolvable source reference): "
        + ", ".join(m.target_field for m in skipped[:8])
        + ("..." if skipped_count > 8 else "")
    ) if skipped else "All fields with source references resolved."

    desc_lines = [
        f"Main automation subflow for {object_api} — generated from CSV spec.",
        f"Field updates mapped: {total_mapped} "
        f"({len(create_fields)} create-only, {len(update_fields)} update-only, "
        f"{len(always_fields)} always).",
        skip_summary,
        "Admin note: review skipped fields and child-rollup fields manually.",
    ]

    root = ET.Element(qname("Flow"))
    add_common_flow_metadata(root)
    add(root, "description", " ".join(desc_lines))
    add(root, "interviewLabel", f"{flow_api} {{!$Flow.CurrentDateTime}}")
    add(root, "label", flow_api.replace("_", " "))

    # ------------------------------------------------------------------
    # Build the connector chain by determining what nodes exist
    # ------------------------------------------------------------------

    # Determine node sequence (terminal is always Log_Main_Subflow_Execution)
    LOG_NODE = "Log_Main_Subflow_Execution"

    # After all lookups (and possibly update-always), what's the next node?
    if has_always and has_conditional:
        after_lookups = "Update_Record_Always"
        after_always = "Decide_Create_Or_Update"
    elif has_always:
        after_lookups = "Update_Record_Always"
        after_always = LOG_NODE
    elif has_conditional:
        after_lookups = "Decide_Create_Or_Update"
    else:
        after_lookups = LOG_NODE

    # What each parent lookup connects to
    if all_used_parents:
        parent_connector_chain: list[str] = []
        for i, p in enumerate(all_used_parents):
            if i + 1 < len(all_used_parents):
                parent_connector_chain.append(f"Get_{all_used_parents[i + 1]}")
            else:
                parent_connector_chain.append(after_lookups)
        first_after_triggering = f"Get_{all_used_parents[0]}"
    else:
        parent_connector_chain = []
        first_after_triggering = after_lookups

    # ------------------------------------------------------------------
    # recordLookups: Get_Triggering_Record
    # ------------------------------------------------------------------
    add_record_lookup(
        root,
        name="Get_Triggering_Record",
        label="Get Triggering Record",
        connector_target=first_after_triggering,
        filter_field="Id",
        filter_element_ref="inRecordId",
        object_api=object_api,
    )

    # ------------------------------------------------------------------
    # recordLookups: each needed parent
    # ------------------------------------------------------------------
    for idx, parent_obj in enumerate(all_used_parents):
        lookup_field = parent_lookup_map[parent_obj]
        add_record_lookup(
            root,
            name=f"Get_{parent_obj}",
            label=f"Get {parent_obj}",
            connector_target=parent_connector_chain[idx],
            filter_field="Id",
            filter_element_ref=f"Get_Triggering_Record.{lookup_field}",
            object_api=parent_obj,
        )

    # ------------------------------------------------------------------
    # recordUpdates: always fields
    # ------------------------------------------------------------------
    if has_always:
        always_assignments = [
            (m.target_field, _source_element_ref(m, object_api))
            for m in always_fields
        ]
        add_record_update(
            root,
            name="Update_Record_Always",
            label="Update Record — Always Fields",
            connector_target=after_always,
            field_assignments=always_assignments,
            id_element_ref="inRecordId",
            object_api=object_api,
        )

    # ------------------------------------------------------------------
    # decisions: create vs. update (only when at least one side has fields)
    # ------------------------------------------------------------------
    if has_conditional:
        yes_create_target = "Update_Record_Create" if has_create else LOG_NODE
        no_target = "Update_Record_Update" if has_update else LOG_NODE

        dec = add(root, "decisions")
        add(dec, "name", "Decide_Create_Or_Update")
        add(dec, "label", "Create or Update?")
        add(dec, "locationX", "0")
        add(dec, "locationY", "0")
        add(add(dec, "defaultConnector"), "targetReference", no_target)
        add(dec, "defaultConnectorLabel", "Update")
        rule = add(dec, "rules")
        add(rule, "name", "Is_Create")
        add(rule, "conditionLogic", "and")
        cond = add(rule, "conditions")
        add(cond, "leftValueReference", "inIsNewRecord")
        add(cond, "operator", "EqualTo")
        add(add(cond, "rightValue"), "booleanValue", "true")
        add(add(rule, "connector"), "targetReference", yes_create_target)
        add(rule, "label", "Create")

        # recordUpdates: create-only fields
        if has_create:
            create_assignments = [
                (m.target_field, _source_element_ref(m, object_api))
                for m in create_fields
            ]
            add_record_update(
                root,
                name="Update_Record_Create",
                label="Update Record — Create-Only Fields",
                connector_target=LOG_NODE,
                field_assignments=create_assignments,
                id_element_ref="inRecordId",
                object_api=object_api,
            )

        # recordUpdates: update-only fields
        if has_update:
            update_assignments = [
                (m.target_field, _source_element_ref(m, object_api))
                for m in update_fields
            ]
            add_record_update(
                root,
                name="Update_Record_Update",
                label="Update Record — Update-Only Fields",
                connector_target=LOG_NODE,
                field_assignments=update_assignments,
                id_element_ref="inRecordId",
                object_api=object_api,
            )

    # ------------------------------------------------------------------
    # subflows: Log_Main_Subflow_Execution (terminal)
    # ------------------------------------------------------------------
    add_log_subflow(
        root,
        name=LOG_NODE,
        label="Log Main Subflow Execution",
        action="MAIN_SUBFLOW",
        message_element_reference=None,
        message_string=(
            f"Mapped {total_mapped} field(s). "
            f"{len(create_fields)} create-only, {len(update_fields)} update-only, "
            f"{len(always_fields)} always. Skipped {skipped_count} (no source)."
        ),
        flow_api_name=flow_api,
        object_api=object_api,
        record_reference="inRecordId",
        correlation_reference="inCorrelationId",
        required_level="INFO",
    )

    # ------------------------------------------------------------------
    # Start
    # ------------------------------------------------------------------
    start = add(root, "start")
    add(start, "locationX", "0")
    add(start, "locationY", "0")
    add(add(start, "connector"), "targetReference", "Get_Triggering_Record")

    add(root, "status", "Draft")

    # ------------------------------------------------------------------
    # Variables
    # ------------------------------------------------------------------
    for var_name, data_type, is_input, is_output in (
        ("inCorrelationId", "String", True, False),
        ("inIsNewRecord", "Boolean", True, False),
        ("inRecordId", "String", True, False),
        ("outRunSummary", "String", False, True),
    ):
        var = add(root, "variables")
        add(var, "name", var_name)
        add(var, "dataType", data_type)
        add(var, "isCollection", "false")
        add(var, "isInput", "true" if is_input else "false")
        add(var, "isOutput", "true" if is_output else "false")

    return root


# ---------------------------------------------------------------------------
# Write + YAML loader
# ---------------------------------------------------------------------------

def write_flow(path: Path, root: ET.Element) -> None:
    ET.indent(root, space="    ")
    tree = ET.ElementTree(root)
    tree.write(path, encoding="UTF-8", xml_declaration=True)


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
            if stripped and ":" in stripped:
                key, value = [p.strip() for p in stripped.split(":", 1)]
                current[key] = value.strip("\"'")
            continue
        if current is None or ":" not in stripped:
            continue
        key, value = [p.strip() for p in stripped.split(":", 1)]
        current[key] = value.strip("\"'")
    if current:
        objects.append(current)
    return objects


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    configs = parse_simple_yaml(CONFIG_PATH)
    if not configs:
        raise SystemExit(f"No objects configured in {CONFIG_PATH}")

    FLOWS_DIR.mkdir(parents=True, exist_ok=True)

    for config in configs:
        csv_path = REPO_ROOT / config["csv_spec"]
        mappings = load_csv_field_mappings(csv_path, config["object_api"])

        router_api = f"RTF_{config['object_api']}_AfterSave_TV"
        router_path = FLOWS_DIR / f"{router_api}.flow-meta.xml"
        write_flow(router_path, generate_router_flow(config))

        main_path = FLOWS_DIR / f"{config['main_subflow_api']}.flow-meta.xml"
        write_flow(main_path, generate_main_subflow(config, mappings))

        resolvable = sum(
            1
            for m in mappings
            if m.source_parent and (
                m.source_parent == config["object_api"]
                or m.source_parent in parse_parent_lookups(config.get("parent_lookups", ""))
            )
        )
        print(
            f"Generated: {router_path.relative_to(REPO_ROOT)} + "
            f"{main_path.name} "
            f"({resolvable}/{len(mappings)} fields mapped)"
        )


if __name__ == "__main__":
    main()
