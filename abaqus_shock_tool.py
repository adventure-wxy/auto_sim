from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from tkinter import (
    BooleanVar,
    Canvas,
    END,
    LEFT,
    RIGHT,
    BOTH,
    PhotoImage,
    TclError,
    X,
    Y,
    StringVar,
    Text,
    Tk,
    Toplevel,
    filedialog,
    messagebox,
    simpledialog,
)
from tkinter import ttk


APP_TITLE = "Abaqus Case Generator"
CONFIG_FILE = Path(__file__).with_name("shock_standards.json")
MODEL_COPY_NAME = "SHOCK_Model.inp"
DIRECTION_IMAGE_FILE = Path(__file__).with_name("image.png")
LAST_RUN_KEY = "last_run"
CASE_TYPE_SHOCK = "Shock"
CASE_TYPE_PACKAGE_DROP = "Package Drop"
PACKAGE_DROP_STANDARDS_KEY = "package_drop_standards"
PACKAGE_DROP_DIRECTIONS_KEY = "package_drop_directions"
PACKAGE_DROP_ADVANCED_KEY = "package_drop_advanced_defaults"
WOOD_COMPONENTS = {
    "lr": "LR_3D_WOOD",
    "ud": "UD_3D_WOOD",
    "fb": "FB_3D_WOOD",
}
DIRECTION_WOOD_COMPONENT = {
    "left": "lr",
    "right": "lr",
    "up": "ud",
    "down": "ud",
    "front": "fb",
    "back": "fb",
}
PACKAGE_DROP_COMPONENTS = {
    "up": "UP_2D_TT0p1_STEEL",
    "down": "DOWN_2D_TT0p1_STEEL",
    "front": "FRONT_2D_TT0p1_STEEL",
    "back": "BACK_2D_TT0p1_STEEL",
    "left": "LEFT_2D_TT0p1_STEEL",
    "right": "RIGHT_2D_TT0p1_STEEL",
}


DEFAULT_DIRECTIONS = {
    "up": {"label": "Up", "axis": 2, "sign": 1},
    "down": {"label": "Down", "axis": 2, "sign": -1},
    "left": {"label": "Left", "axis": 1, "sign": 1},
    "right": {"label": "Right", "axis": 1, "sign": -1},
    "back": {"label": "Back", "axis": 3, "sign": 1},
    "front": {"label": "Front", "axis": 3, "sign": -1},
}

DEFAULT_PACKAGE_DROP_DIRECTIONS = {
    "up": {"label": "Up", "axis": 2, "sign": 1},
    "down": {"label": "Down", "axis": 2, "sign": -1},
    "right": {"label": "Right", "axis": 1, "sign": 1},
    "left": {"label": "Left", "axis": 1, "sign": -1},
    "front": {"label": "Front", "axis": 3, "sign": 1},
    "back": {"label": "Back", "axis": 3, "sign": -1},
}


DEFAULT_ADVANCED = {
    "friction": "0.2",
    "analysis_time": "0.015",
    "mass_scaling_dt": "1.2e-07",
    "field_output_interval": "50",
    "history_interval": "0.015e-03",
    "gravity": "9810.",
    "abaqus_command": "abq2021",
    "cpus": "8",
}

DEFAULT_PACKAGE_DROP_ADVANCED = {
    **DEFAULT_ADVANCED,
    "analysis_time": "0.025",
    "mass_scaling_dt": "1.8e-07",
}

DEFAULT_PACKAGE_DROP_STANDARDS = [
    {
        "name": "Ali",
        "description": "Seed data from Ali_40kg_Package_Drop_6_back reference case.",
        "weight_classes": [
            {
                "name": "40kg",
                "job_prefix": "Ali_40kg_Package_Drop",
                "velocity": 3834.0,
            }
        ],
    }
]


DEFAULT_CONFIG = {
    "directions": DEFAULT_DIRECTIONS,
    PACKAGE_DROP_DIRECTIONS_KEY: DEFAULT_PACKAGE_DROP_DIRECTIONS,
    "standards": [
        {
            "name": "Reference",
            "description": "Seed data from Ali_40kg_Shock_1_up reference case.",
            "weight_classes": [
                {
                    "name": "40kg_up_reference",
                    "job_prefix": "Ali_40kg_Shock_1",
                    "velocity": 4315.0,
                    "acceleration": 40.0,
                    "shock_time_ms": 11.0,
                }
            ],
        }
    ],
    "advanced_defaults": DEFAULT_ADVANCED,
    PACKAGE_DROP_ADVANCED_KEY: DEFAULT_PACKAGE_DROP_ADVANCED,
    PACKAGE_DROP_STANDARDS_KEY: DEFAULT_PACKAGE_DROP_STANDARDS,
}


@dataclass(frozen=True)
class CaseSpec:
    job_name: str
    direction_key: str
    direction_label: str
    axis: int
    sign: int
    velocity: float
    acceleration: float
    shock_time_ms: float


def ensure_config(path: Path = CONFIG_FILE) -> dict:
    if not path.exists():
        save_config(DEFAULT_CONFIG, path)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    data.setdefault("directions", DEFAULT_DIRECTIONS)
    data.setdefault(PACKAGE_DROP_DIRECTIONS_KEY, DEFAULT_PACKAGE_DROP_DIRECTIONS)
    data.setdefault("standards", DEFAULT_CONFIG["standards"])
    data.setdefault("advanced_defaults", DEFAULT_ADVANCED)
    data.setdefault(PACKAGE_DROP_ADVANCED_KEY, DEFAULT_PACKAGE_DROP_ADVANCED)
    data.setdefault(PACKAGE_DROP_STANDARDS_KEY, DEFAULT_PACKAGE_DROP_STANDARDS)
    return data


def save_config(data: dict, path: Path = CONFIG_FILE) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)


def as_float(value: str | float | int, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number: {value}") from exc


def as_int(value: str | int, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer: {value}") from exc


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    cleaned = cleaned.strip("._")
    return cleaned or "case"


def unique_directory(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.name}_{index:03d}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not create a unique folder for {path}")


def build_job_name(weight_class: dict, direction_key: str) -> str:
    prefix = weight_class.get("job_prefix") or weight_class.get("name") or "Shock"
    return safe_name(f"{prefix}_{direction_key}")


def make_case_spec(weight_class: dict, direction_key: str, direction: dict) -> CaseSpec:
    return CaseSpec(
        job_name=build_job_name(weight_class, direction_key),
        direction_key=direction_key,
        direction_label=direction.get("label", direction_key),
        axis=as_int(direction.get("axis"), "direction axis"),
        sign=1 if as_int(direction.get("sign"), "direction sign") >= 0 else -1,
        velocity=as_float(weight_class.get("velocity"), "velocity"),
        acceleration=as_float(weight_class.get("acceleration", 0.0), "acceleration"),
        shock_time_ms=as_float(weight_class.get("shock_time_ms", 11.0), "shock time"),
    )


def format_num(value: float | str) -> str:
    if isinstance(value, str):
        return value
    text = f"{value:.12g}"
    return text if "." in text or "e" in text.lower() else f"{text}."


def render_boundary_lines_with_base(spec: CaseSpec, base_acceleration: float) -> str:
    lines = []
    for dof in range(1, 7):
        value = -spec.sign * base_acceleration if dof == spec.axis else 0.0
        lines.append(f"Nset_SHOCK_BC, {dof}, {dof}, {format_num(value)}")
    return "\n".join(lines)


def shock_amplitude_times(shock_time_ms: float) -> tuple[float, float]:
    plateau_end = 0.0001 + shock_time_ms / 1000.0
    zero_time = plateau_end + 0.0001
    return plateau_end, zero_time


def direction_vector(spec: CaseSpec) -> tuple[str, str, str]:
    values = [0.0, 0.0, 0.0]
    values[spec.axis - 1] = float(spec.sign)
    return tuple(format_num(value) for value in values)


def quote_abaqus_name(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def parse_output_names(text: str) -> list[str]:
    names: list[str] = []
    seen = set()
    for raw_name in re.split(r"[\n,;]+", text):
        name = raw_name.strip().strip('"')
        if name and name not in seen:
            names.append(name)
            seen.add(name)
    return names


def render_output_requests(contact_surface_names: list[str], section_names: list[str], history_interval: str) -> str:
    lines: list[str] = []
    for name in contact_surface_names:
        lines.extend([
            f"*CONTACT OUTPUT, SURFACE = {quote_abaqus_name(name)}",
            "CFN,",
        ])
    for name in section_names:
        quoted_name = quote_abaqus_name(name)
        lines.extend([
            f"*OUTPUT, HISTORY, NAME ={quoted_name}, TIME INTERVAL = {history_interval}",
            f"*INTEGRATED OUTPUT, SECTION ={quoted_name}",
        ])
    return "\n".join(lines)


def without_blank_lines(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if line.strip()) + "\n"


def render_inp(
    spec: CaseSpec,
    advanced: dict,
    contact_surface_names: list[str] | None = None,
    section_names: list[str] | None = None,
) -> str:
    analysis_time = advanced["analysis_time"]
    history_interval = advanced["history_interval"]
    friction = advanced["friction"]
    mass_dt = advanced["mass_scaling_dt"]
    field_interval = advanced["field_output_interval"]
    gravity = advanced["gravity"]
    velocity_value = spec.sign * spec.velocity
    amplitude_plateau_end, amplitude_zero_time = shock_amplitude_times(spec.shock_time_ms)
    boundary_lines = render_boundary_lines_with_base(spec, as_float(gravity, "gravity"))
    gravity_x, gravity_y, gravity_z = direction_vector(spec)
    output_requests = render_output_requests(
        contact_surface_names or [],
        section_names or [],
        history_interval,
    )

    return without_blank_lines(f"""*INCLUDE,INPUT={MODEL_COPY_NAME}
** Surface interaction, tangential friction coefficient
*Surface Interaction, name=IntProp-1
*Friction
 {friction},
***FILTER , NAME = BW, TYPE = BUTTERWORTH
**180.0      ,          2
** Acceleration load curve definition
*Amplitude, name=Amp-1
0.,                  0.,
0.0001,              {format_num(spec.acceleration)},
{format_num(amplitude_plateau_end)},              {format_num(spec.acceleration)},
{format_num(amplitude_zero_time)},               0.,
{analysis_time},               0.,
** Initial velocity, direction={spec.direction_label}, axis={spec.axis}
*Initial Conditions, type=VELOCITY
ALL_Nset,{spec.axis},{format_num(velocity_value)}
** ----------------------------------------------------------------
** Explicit dynamic step
*Step, name=Step-1, nlgeom=YES
*Dynamic, Explicit
, {analysis_time},,
*Bulk Viscosity
0.06, 1.2
** Variable mass scaling
*Variable Mass Scaling, dt={mass_dt}, type=below min, frequency=100
** Shock boundary condition, acceleration is opposite to initial velocity direction
*Boundary, amplitude=Amp-1, type=ACCELERATION
{boundary_lines}
** Gravity field
*Dload
ALL_Element, GRAV, {gravity}, {gravity_x}, {gravity_y}, {gravity_z}
** General contact
*Contact, op=NEW
*Contact Inclusions, ALL EXTERIOR
*Contact Property Assignment
 ,  , IntProp-1
** Field output
*Restart, write, number interval=1, time marks=NO
**
** FIELD OUTPUT: F-Output-1
**
*Output, field, number interval={field_interval}
*Node Output
U,
*Element Output, directions=YES
LE, PEEQ, S
*Contact Output
CFORCE,
** History output
*OUTPUT, HISTORY, NAME =ENERGY, TIME INTERVAL = {history_interval}
*ENERGY OUTPUT
ALLAE,
ALLIE,
ALLKE,
ALLWK,
ETOTAL,
{output_requests}
****************************************************************************************************
*END STEP
""")


def render_package_drop_inp(
    spec: CaseSpec,
    advanced: dict,
    contact_surface_names: list[str] | None = None,
    section_names: list[str] | None = None,
) -> str:
    analysis_time = advanced["analysis_time"]
    history_interval = advanced["history_interval"]
    friction = advanced["friction"]
    mass_dt = advanced["mass_scaling_dt"]
    field_interval = advanced["field_output_interval"]
    gravity = advanced["gravity"]
    velocity_value = spec.sign * spec.velocity
    gravity_x, gravity_y, gravity_z = direction_vector(spec)
    output_requests = render_output_requests(
        contact_surface_names or [],
        section_names or [],
        history_interval,
    )

    return without_blank_lines(f"""*INCLUDE,INPUT={MODEL_COPY_NAME}
********************************************************************************************************************
*SURFACE INTERACTION, NAME = Fric
*FRICTION
{friction}       , 0.0       ,0.0       ,0.0
********************************************************************************************************************
*AMPLITUDE, NAME =Curve_Grav, DEFINITION = TABULAR
0.0       ,1.0
{analysis_time}     ,1.0
********************************************************************************************************************
*INITIAL CONDITIONS, TYPE = VELOCITY
ALL_Nset,{spec.axis},{format_num(velocity_value)}
********************************************************************************************************************
*STEP, NLGEOM = YES
*DYNAMIC, EXPLICIT
          ,     {analysis_time},          ,
*DLOAD, AMPLITUDE = Curve_Grav
ALL_Element,GRAV,{gravity},{gravity_x},{gravity_y},{gravity_z}
*BOUNDARY
SPC_Rack_Shock,1,6,0
*CONTACT
*CONTACT INCLUSIONS, ALL EXTERIOR
*CONTACT PROPERTY ASSIGNMENT
, , Fric
*VARIABLE MASS SCALING, DT = {mass_dt}, TYPE = BELOW MIN, NUMBER INTERVAL =        50
*OUTPUT, FIELD, NAME = U, , NUMBER INTERVAL = {field_interval}
*NODE OUTPUT
U,
*OUTPUT, FIELD, NAME = S, NUMBER INTERVAL = {field_interval}
*ELEMENT OUTPUT
S,
PEEQ,
LE,
*CONTACT OUTPUT
CFORCE,CSTATUS
****************************************************************************************************
*OUTPUT, HISTORY, NAME =ENERGY, TIME INTERVAL = {history_interval}
*ENERGY OUTPUT
ALLAE,
ALLIE,
ALLKE,
ALLWK,
ETOTAL,
{output_requests}
****************************************************************************************************
*END STEP
""")


def render_bat(job_name: str, advanced: dict) -> str:
    command = advanced["abaqus_command"].strip() or "abq2021"
    cpus = advanced["cpus"].strip() or "8"
    return f'cd /d "%~dp0"\ncall {command} job={job_name} cpus={cpus} int\n'


def common_job_prefix(specs: list[CaseSpec]) -> str:
    if not specs:
        return "cases"
    suffix = f"_{specs[0].direction_key}"
    first = specs[0].job_name
    return first[: -len(suffix)] if first.endswith(suffix) else first


def build_multi_task_name(specs: list[CaseSpec]) -> str:
    return safe_name(f"{common_job_prefix(specs)}_{'_'.join(spec.direction_key for spec in specs)}")


def render_multi_task_bat(case_dirs: list[Path], specs: list[CaseSpec]) -> str:
    lines = []
    for case_dir, spec in zip(case_dirs, specs):
        lines.append(f'call "{case_dir.name}\\{spec.job_name}.bat"')
    return "\n".join(lines) + "\n"


def write_multi_task_bat(output_root: Path, case_dirs: list[Path], specs: list[CaseSpec]) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    bat_path = output_root / f"{build_multi_task_name(specs)}.bat"
    bat_path.write_text(render_multi_task_bat(case_dirs, specs), encoding="utf-8")
    return bat_path


def keyword_blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.upper().startswith("**HW_COMPONENT"):
            if current:
                blocks.append(current)
            current = [line]
            continue
        is_keyword = stripped.startswith("*") and not stripped.startswith("**")
        if is_keyword and current and keyword_header(current):
            blocks.append(current)
            current = []
        current.append(line)
    if current:
        blocks.append(current)
    return blocks


def keyword_header(block: list[str]) -> str:
    for line in block:
        stripped = line.lstrip()
        if stripped.startswith("*") and not stripped.startswith("**"):
            return line.strip()
    return ""


def keyword_header_index(block: list[str]) -> int:
    for index, line in enumerate(block):
        stripped = line.lstrip()
        if stripped.startswith("*") and not stripped.startswith("**"):
            return index
    return -1


def keyword_name(header: str) -> str:
    return header.split(",", 1)[0].strip().lower()


def keyword_param(header: str, name: str) -> str:
    match = re.search(rf"(?:^|[,\s]){re.escape(name)}\s*=\s*(\"[^\"]+\"|[^,\s]+)", header, flags=re.IGNORECASE)
    return match.group(1).strip().strip('"') if match else ""


def component_token_match(text: str, components: set[str]) -> bool:
    lowered = text.lower()
    return any(component.lower() in lowered for component in components)


def hw_component_name(block: list[str]) -> str:
    for line in block:
        if line.lstrip().upper().startswith("**HW_COMPONENT"):
            return keyword_param(line, "name")
    return ""


def components_to_remove(
    direction_key: str,
    components: dict[str, str],
    direction_component: dict[str, str],
) -> set[str]:
    keep_key = direction_component.get(direction_key)
    if not keep_key:
        return set()
    return {name for key, name in components.items() if key != keep_key}


def wood_components_to_remove(direction_key: str) -> set[str]:
    return components_to_remove(direction_key, WOOD_COMPONENTS, DIRECTION_WOOD_COMPONENT)


def package_drop_components_to_remove(direction_key: str) -> set[str]:
    return components_to_remove(direction_key, PACKAGE_DROP_COMPONENTS, {key: key for key in PACKAGE_DROP_COMPONENTS})


def read_model_text(model_path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp936"):
        try:
            return model_path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return model_path.read_text(encoding="utf-8", errors="replace")


def parse_int_tokens(line: str) -> list[int]:
    values: list[int] = []
    for token in line.split(","):
        token = token.strip()
        if re.fullmatch(r"[+-]?\d+", token):
            values.append(int(token))
    return values


def element_connectivity(block: list[str]) -> dict[int, set[int]]:
    elements: dict[int, set[int]] = {}
    for line in block[1:]:
        if line.lstrip().startswith("**"):
            continue
        values = parse_int_tokens(line)
        if len(values) >= 2:
            elements[values[0]] = set(values[1:])
    return elements


def block_references_removed_component(block: list[str], components: set[str]) -> bool:
    header = keyword_header(block)
    name = keyword_name(header)
    if name in {"*node", "*element"}:
        return False
    return component_token_match("".join(block), components)


def filter_node_block(block: list[str], nodes_to_delete: set[int]) -> list[str]:
    if not nodes_to_delete:
        return block
    header_index = keyword_header_index(block)
    if header_index < 0:
        return block
    filtered = block[: header_index + 1]
    for line in block[header_index + 1 :]:
        values = parse_int_tokens(line)
        if values and values[0] in nodes_to_delete:
            continue
        filtered.append(line)
    return filtered


def format_set_values(values: list[int]) -> list[str]:
    lines = []
    for index in range(0, len(values), 8):
        chunk = values[index : index + 8]
        suffix = "," if index + 8 < len(values) else ""
        lines.append("".join(f"{value:10d}," for value in chunk).rstrip(",") + suffix + "\n")
    return lines


def filter_id_set_block(block: list[str], ids_to_delete: set[int]) -> list[str]:
    if not ids_to_delete:
        return block
    header_index = keyword_header_index(block)
    if header_index < 0:
        return block
    header = block[header_index]
    if "generate" in header.lower():
        return block

    changed = False
    output = block[: header_index + 1]
    pending_values: list[int] = []
    for line in block[header_index + 1 :]:
        if line.lstrip().startswith("**"):
            if pending_values:
                output.extend(format_set_values(pending_values))
                pending_values = []
            output.append(line)
            continue
        values = parse_int_tokens(line)
        if not values:
            if pending_values:
                output.extend(format_set_values(pending_values))
                pending_values = []
            output.append(line)
            continue
        kept_values = [value for value in values if value not in ids_to_delete]
        changed = changed or len(kept_values) != len(values)
        pending_values.extend(kept_values)
    if pending_values:
        output.extend(format_set_values(pending_values))
    return output if changed else block


def filter_model_components_for_direction(model_text: str, direction_key: str, remove_components: set[str]) -> str:
    if not remove_components:
        return model_text

    blocks = keyword_blocks(model_text.splitlines(keepends=True))
    first_pass: list[tuple[list[str], bool]] = []
    removed_nodes: set[int] = set()
    kept_nodes: set[int] = set()
    removed_elements: set[int] = set()
    kept_elements: set[int] = set()
    skip_part = False
    skip_instance = False

    for block in blocks:
        header = keyword_header(block)
        name = keyword_name(header)
        component_name = hw_component_name(block)
        remove_block = False

        if skip_part:
            remove_block = True
            if name == "*end part":
                skip_part = False
        elif skip_instance:
            remove_block = True
            if name == "*end instance":
                skip_instance = False
        elif name == "*part" and component_token_match(keyword_param(header, "name"), remove_components):
            remove_block = True
            skip_part = True
        elif name == "*instance" and (
            component_token_match(keyword_param(header, "name"), remove_components)
            or component_token_match(keyword_param(header, "part"), remove_components)
        ):
            remove_block = True
            skip_instance = True
        elif name == "*element":
            block_nodes = element_connectivity(block)
            component_reference = component_name or header
            if component_token_match(component_reference, remove_components):
                remove_block = True
                removed_elements.update(block_nodes)
                for nodes in block_nodes.values():
                    removed_nodes.update(nodes)
            else:
                kept_elements.update(block_nodes)
                for nodes in block_nodes.values():
                    kept_nodes.update(nodes)
        elif name in {"*nset", "*elset"} and component_token_match(header, remove_components):
            remove_block = True
        elif block_references_removed_component(block, remove_components):
            remove_block = True

        first_pass.append((block, remove_block))

    nodes_to_delete = removed_nodes - kept_nodes
    elements_to_delete = removed_elements - kept_elements
    output_lines: list[str] = []
    for block, remove_block in first_pass:
        if remove_block:
            continue
        header = keyword_header(block)
        name = keyword_name(header)
        if name == "*node":
            output_lines.extend(filter_node_block(block, nodes_to_delete))
        elif name == "*nset":
            output_lines.extend(filter_id_set_block(block, nodes_to_delete))
        elif name == "*elset":
            output_lines.extend(filter_id_set_block(block, elements_to_delete))
        else:
            output_lines.extend(block)
    return "".join(output_lines)


def filter_model_for_direction(model_text: str, direction_key: str) -> str:
    return filter_model_components_for_direction(model_text, direction_key, wood_components_to_remove(direction_key))


def filter_package_drop_model_for_direction(model_text: str, direction_key: str) -> str:
    return filter_model_components_for_direction(model_text, direction_key, package_drop_components_to_remove(direction_key))


def build_direction_model_text(model_path: Path, direction_key: str) -> str:
    return filter_model_for_direction(read_model_text(model_path), direction_key)


def build_package_drop_model_text(model_path: Path, direction_key: str) -> str:
    return filter_package_drop_model_for_direction(read_model_text(model_path), direction_key)


def generate_case(
    model_path: Path,
    output_root: Path,
    spec: CaseSpec,
    advanced: dict,
    case_type: str = CASE_TYPE_SHOCK,
    conflict_strategy: str = "error",
    rewrite_boundary_file: bool = True,
    contact_surface_names: list[str] | None = None,
    section_names: list[str] | None = None,
) -> Path:
    if not model_path.is_file():
        raise FileNotFoundError(f"Model file not found: {model_path}")
    if output_root.exists() and not output_root.is_dir():
        raise NotADirectoryError(f"Output root is not a directory: {output_root}")

    case_dir = output_root / spec.job_name
    if case_dir.exists():
        if conflict_strategy == "skip":
            return case_dir
        if conflict_strategy == "rename":
            case_dir = unique_directory(case_dir)
        elif conflict_strategy != "overwrite":
            raise FileExistsError(f"Case folder already exists: {case_dir}")

    case_dir.mkdir(parents=True, exist_ok=True)
    if case_type == CASE_TYPE_PACKAGE_DROP:
        (case_dir / MODEL_COPY_NAME).write_text(build_package_drop_model_text(model_path, spec.direction_key), encoding="utf-8")
    else:
        (case_dir / MODEL_COPY_NAME).write_text(build_direction_model_text(model_path, spec.direction_key), encoding="utf-8")
    boundary_path = case_dir / f"{spec.job_name}.inp"
    if rewrite_boundary_file or not boundary_path.exists():
        if case_type == CASE_TYPE_PACKAGE_DROP:
            boundary_text = render_package_drop_inp(spec, advanced, contact_surface_names or [], section_names or [])
        else:
            boundary_text = render_inp(spec, advanced, contact_surface_names or [], section_names or [])
        boundary_path.write_text(
            boundary_text,
            encoding="utf-8",
        )
    bat_path = case_dir / f"{spec.job_name}.bat"
    bat_path.write_text(render_bat(spec.job_name, advanced), encoding="utf-8")

    return case_dir


class StandardsEditor(Toplevel):
    def __init__(self, master: "ShockGeneratorApp") -> None:
        super().__init__(master.root)
        self.master_app = master
        self.standards_key = master.current_standards_key()
        self.uses_acceleration = master.case_type.get() == CASE_TYPE_SHOCK
        self.title(f"{master.case_type.get()} Standards Library")
        self.geometry("760x460")
        self.config_data = master.config_data
        self.selected_standard_index = 0

        outer = ttk.Frame(self, padding=10)
        outer.pack(fill=BOTH, expand=True)

        left = ttk.Frame(outer)
        left.pack(side=LEFT, fill=Y, padx=(0, 10))
        ttk.Label(left, text="Standards").pack(anchor="w")
        self.standard_list = ttk.Treeview(left, columns=("name",), show="headings", height=14)
        self.standard_list.heading("name", text="Name")
        self.standard_list.column("name", width=180)
        self.standard_list.pack(fill=Y, expand=True)
        self.standard_list.bind("<<TreeviewSelect>>", self.on_standard_select)

        standard_buttons = ttk.Frame(left)
        standard_buttons.pack(fill=X, pady=6)
        ttk.Button(standard_buttons, text="Add", command=self.add_standard).pack(side=LEFT)
        ttk.Button(standard_buttons, text="Delete", command=self.delete_standard).pack(side=LEFT, padx=4)

        right = ttk.Frame(outer)
        right.pack(side=RIGHT, fill=BOTH, expand=True)

        ttk.Label(right, text="Standard name").pack(anchor="w")
        self.standard_name = StringVar()
        ttk.Entry(right, textvariable=self.standard_name).pack(fill=X)
        ttk.Button(right, text="Update Name", command=self.update_standard_name).pack(anchor="e", pady=4)

        ttk.Label(right, text="Weight classes").pack(anchor="w", pady=(8, 0))
        self.weight_tree = ttk.Treeview(
            right,
            columns=("name", "prefix", "velocity", "acceleration", "shock_time_ms"),
            show="headings",
            height=10,
        )
        columns = [
            ("name", "Name", 150),
            ("prefix", "Job Prefix", 180),
            ("velocity", "Velocity", 100),
        ]
        if self.uses_acceleration:
            columns.append(("acceleration", "Acceleration", 110))
            columns.append(("shock_time_ms", "Shock time ms", 110))
        else:
            self.weight_tree["displaycolumns"] = ("name", "prefix", "velocity")
        for column, label, width in columns:
            self.weight_tree.heading(column, text=label)
            self.weight_tree.column(column, width=width)
        self.weight_tree.pack(fill=BOTH, expand=True)

        weight_buttons = ttk.Frame(right)
        weight_buttons.pack(fill=X, pady=6)
        ttk.Button(weight_buttons, text="Add Weight", command=self.add_weight).pack(side=LEFT)
        ttk.Button(weight_buttons, text="Edit Weight", command=self.edit_weight).pack(side=LEFT, padx=4)
        ttk.Button(weight_buttons, text="Delete Weight", command=self.delete_weight).pack(side=LEFT)
        ttk.Button(right, text="Save Library", command=self.save).pack(anchor="e", pady=(8, 0))

        self.refresh_standards()

    def standards(self) -> list[dict]:
        return self.config_data.setdefault(self.standards_key, [])

    def current_standard(self) -> dict | None:
        standards = self.standards()
        if not standards:
            return None
        self.selected_standard_index = max(0, min(self.selected_standard_index, len(standards) - 1))
        return standards[self.selected_standard_index]

    def refresh_standards(self) -> None:
        self.standard_list.delete(*self.standard_list.get_children())
        for index, standard in enumerate(self.standards()):
            self.standard_list.insert("", END, iid=str(index), values=(standard.get("name", f"Standard {index + 1}"),))
        if self.standards():
            self.standard_list.selection_set(str(self.selected_standard_index))
        self.refresh_weights()

    def refresh_weights(self) -> None:
        self.weight_tree.delete(*self.weight_tree.get_children())
        standard = self.current_standard()
        if not standard:
            self.standard_name.set("")
            return
        self.standard_name.set(standard.get("name", ""))
        for index, weight in enumerate(standard.setdefault("weight_classes", [])):
            self.weight_tree.insert(
                "",
                END,
                iid=str(index),
                values=(
                    weight.get("name", ""),
                    weight.get("job_prefix", ""),
                    weight.get("velocity", ""),
                    weight.get("acceleration", ""),
                    weight.get("shock_time_ms", 11.0),
                ),
            )

    def on_standard_select(self, _event=None) -> None:
        selection = self.standard_list.selection()
        if selection:
            self.selected_standard_index = int(selection[0])
        self.refresh_weights()

    def add_standard(self) -> None:
        name = simpledialog.askstring("Add Standard", "Standard name:", parent=self)
        if not name:
            return
        self.standards().append({"name": name, "description": "", "weight_classes": []})
        self.selected_standard_index = len(self.standards()) - 1
        self.refresh_standards()

    def delete_standard(self) -> None:
        if not self.current_standard():
            return
        if not messagebox.askyesno("Delete", "Delete selected standard?", parent=self):
            return
        del self.standards()[self.selected_standard_index]
        self.selected_standard_index = 0
        self.refresh_standards()

    def update_standard_name(self) -> None:
        standard = self.current_standard()
        if standard:
            standard["name"] = self.standard_name.get().strip() or "Unnamed"
            self.refresh_standards()

    def prompt_weight(self, initial: dict | None = None) -> dict | None:
        initial = initial or {}
        name = simpledialog.askstring("Weight Class", "Weight class name:", initialvalue=initial.get("name", ""), parent=self)
        if not name:
            return None
        prefix = simpledialog.askstring(
            "Weight Class",
            "Job name prefix:",
            initialvalue=initial.get("job_prefix", safe_name(name)),
            parent=self,
        )
        if not prefix:
            return None
        velocity = simpledialog.askfloat(
            "Weight Class",
            "Initial velocity (mm/s):",
            initialvalue=float(initial.get("velocity", 0) or 0),
            parent=self,
        )
        if velocity is None:
            return None
        acceleration = simpledialog.askfloat(
            "Weight Class",
            "Shock acceleration / amplitude peak:",
            initialvalue=float(initial.get("acceleration", 0) or 0),
            parent=self,
        ) if self.uses_acceleration else None
        if self.uses_acceleration and acceleration is None:
            return None
        shock_time_ms = simpledialog.askfloat(
            "Weight Class",
            "Shock time (ms):",
            initialvalue=float(initial.get("shock_time_ms", 11.0) or 11.0),
            parent=self,
        ) if self.uses_acceleration else None
        if self.uses_acceleration and shock_time_ms is None:
            return None
        weight = {
            "name": name.strip(),
            "job_prefix": safe_name(prefix),
            "velocity": velocity,
        }
        if self.uses_acceleration:
            weight["acceleration"] = acceleration
            weight["shock_time_ms"] = shock_time_ms
        return weight

    def add_weight(self) -> None:
        standard = self.current_standard()
        if not standard:
            return
        weight = self.prompt_weight()
        if weight:
            standard.setdefault("weight_classes", []).append(weight)
            self.refresh_weights()

    def edit_weight(self) -> None:
        standard = self.current_standard()
        selection = self.weight_tree.selection()
        if not standard or not selection:
            return
        index = int(selection[0])
        weights = standard.setdefault("weight_classes", [])
        updated = self.prompt_weight(weights[index])
        if updated:
            weights[index] = updated
            self.refresh_weights()

    def delete_weight(self) -> None:
        standard = self.current_standard()
        selection = self.weight_tree.selection()
        if not standard or not selection:
            return
        del standard.setdefault("weight_classes", [])[int(selection[0])]
        self.refresh_weights()

    def save(self) -> None:
        self.update_standard_name()
        save_config(self.config_data)
        self.master_app.reload_config()
        messagebox.showinfo("Saved", "Standards library saved.", parent=self)


class ShockGeneratorApp:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("920x680")
        self.config_data = ensure_config()
        self.last_run_state = self.config_data.get(LAST_RUN_KEY, {})
        self.case_type = StringVar(value=self.last_run_state.get("case_type", CASE_TYPE_SHOCK))
        last_advanced = self.last_run_state.get(
            "advanced",
            self.default_advanced_for_case_type(),
        )
        self.last_direction_keys = set(self.last_run_state.get("directions", ["up"]))
        self.last_contact_surface_names = self.last_run_state.get("contact_surface_names", [])
        self.last_section_names = self.last_run_state.get("section_names", [])

        self.model_path = StringVar(value=self.last_run_state.get("model_path", str(Path("Ali_40kg_Shock_1_up") / MODEL_COPY_NAME)))
        self.output_root = StringVar(value=self.last_run_state.get("output_root", str(Path.cwd() / "generated_cases")))
        self.standard_name = StringVar(value=self.last_run_state.get("standard", ""))
        self.weight_name = StringVar(value=self.last_run_state.get("weight", ""))
        self.submit_after_generate = BooleanVar(value=bool(self.last_run_state.get("submit_after_generate", False)))
        self.rewrite_boundary_file = BooleanVar(value=bool(self.last_run_state.get("rewrite_boundary_file", True)))
        self.conflict_strategy = StringVar(value=self.last_run_state.get("conflict_strategy", "rename"))
        self.direction_vars: dict[str, BooleanVar] = {}
        self.advanced_vars = {
            key: StringVar(value=str(last_advanced.get(key, value)))
            for key, value in DEFAULT_ADVANCED.items()
        }

        self.build_ui()
        self.reload_config()

    def build_ui(self) -> None:
        root_frame = self.create_scrollable_root()

        paths = ttk.LabelFrame(root_frame, text="Paths", padding=10)
        paths.pack(fill=X)
        self.path_row(paths, "Model file", self.model_path, self.choose_model)
        self.path_row(paths, "Output root", self.output_root, self.choose_output)

        selection = ttk.LabelFrame(root_frame, text="Case Selection", padding=10)
        selection.pack(fill=X, pady=10)
        ttk.Label(selection, text="Case type").grid(row=0, column=0, sticky="w")
        self.case_type_combo = ttk.Combobox(
            selection,
            textvariable=self.case_type,
            state="readonly",
            width=28,
            values=(CASE_TYPE_SHOCK, CASE_TYPE_PACKAGE_DROP),
        )
        self.case_type_combo.grid(row=0, column=1, sticky="ew", padx=6)
        self.case_type_combo.bind("<<ComboboxSelected>>", lambda _event: self.on_case_type_change())

        ttk.Label(selection, text="Standard").grid(row=1, column=0, sticky="w", pady=6)
        self.standard_combo = ttk.Combobox(selection, textvariable=self.standard_name, state="readonly", width=28)
        self.standard_combo.grid(row=1, column=1, sticky="ew", padx=6, pady=6)
        self.standard_combo.bind("<<ComboboxSelected>>", lambda _event: self.on_standard_change())
        ttk.Button(selection, text="Edit Standards", command=self.open_standards_editor).grid(row=1, column=2, padx=6)

        ttk.Label(selection, text="Weight").grid(row=2, column=0, sticky="w", pady=6)
        self.weight_combo = ttk.Combobox(selection, textvariable=self.weight_name, state="readonly", width=28)
        self.weight_combo.grid(row=2, column=1, sticky="ew", padx=6, pady=6)

        ttk.Label(selection, text="Directions").grid(row=3, column=0, sticky="w")
        directions_frame = ttk.Frame(selection)
        directions_frame.grid(row=3, column=1, columnspan=2, sticky="w", pady=4)
        for key in DEFAULT_DIRECTIONS:
            var = BooleanVar(value=(key in self.last_direction_keys))
            self.direction_vars[key] = var
            ttk.Checkbutton(
                directions_frame,
                text=DEFAULT_DIRECTIONS[key]["label"],
                variable=var,
            ).pack(side=LEFT, padx=(0, 10))
        self.add_direction_image(selection)
        selection.columnconfigure(1, weight=1)

        advanced = ttk.LabelFrame(root_frame, text="Advanced Parameters", padding=10)
        advanced.pack(fill=X, pady=(0, 10))
        labels = {
            "friction": "Friction",
            "analysis_time": "Analysis time",
            "mass_scaling_dt": "Mass scaling dt",
            "field_output_interval": "Field output interval",
            "history_interval": "History interval",
            "gravity": "Gravity",
            "abaqus_command": "Abaqus command",
            "cpus": "CPUs",
        }
        for index, key in enumerate(DEFAULT_ADVANCED):
            row = index // 4
            col = (index % 4) * 2
            ttk.Label(advanced, text=labels[key]).grid(row=row, column=col, sticky="w", padx=(0, 4), pady=3)
            ttk.Entry(advanced, textvariable=self.advanced_vars[key], width=16).grid(row=row, column=col + 1, sticky="ew", padx=(0, 10), pady=3)
        for col in range(8):
            advanced.columnconfigure(col, weight=1 if col % 2 else 0)

        output_requests = ttk.LabelFrame(root_frame, text="Output Requests", padding=10)
        output_requests.pack(fill=X, pady=(0, 10))
        ttk.Label(output_requests, text="Contact SURFACE names").grid(row=0, column=0, sticky="w")
        ttk.Label(output_requests, text="Section names").grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.contact_surface_text = Text(output_requests, height=3, width=44, wrap="none")
        self.section_text = Text(output_requests, height=3, width=44, wrap="none")
        self.contact_surface_text.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.section_text.grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=(4, 0))
        self.set_names_text(self.contact_surface_text, self.last_contact_surface_names)
        self.set_names_text(self.section_text, self.last_section_names)
        output_requests.columnconfigure(0, weight=1)
        output_requests.columnconfigure(1, weight=1)

        actions = ttk.Frame(root_frame)
        actions.pack(fill=X, pady=10)
        ttk.Label(actions, text="Existing folder").pack(side=LEFT)
        ttk.Combobox(
            actions,
            textvariable=self.conflict_strategy,
            state="readonly",
            width=12,
            values=("rename", "overwrite", "skip"),
        ).pack(side=LEFT, padx=6)
        ttk.Checkbutton(actions, text="Rewrite boundary file", variable=self.rewrite_boundary_file).pack(side=LEFT, padx=12)
        ttk.Checkbutton(actions, text="Submit after generate", variable=self.submit_after_generate).pack(side=LEFT, padx=12)
        self.generate_button = ttk.Button(actions, text="Generate Cases", command=self.generate_cases)
        self.generate_button.pack(side=RIGHT)

        progress_frame = ttk.Frame(root_frame)
        progress_frame.pack(fill=X, pady=(0, 10))
        self.progress_var = StringVar(value="Ready")
        self.progress_bar = ttk.Progressbar(progress_frame, mode="determinate", maximum=100)
        self.progress_bar.pack(side=LEFT, fill=X, expand=True)
        ttk.Label(progress_frame, textvariable=self.progress_var, width=28, anchor="e").pack(side=RIGHT, padx=(10, 0))

        log_frame = ttk.LabelFrame(root_frame, text="Log", padding=8)
        log_frame.pack(fill=BOTH, expand=True)
        self.log_text = ttk.Treeview(log_frame, columns=("message",), show="headings", height=5)
        self.log_text.heading("message", text="Message")
        self.log_text.column("message", width=840)
        self.log_text.pack(fill=BOTH, expand=True)

    def create_scrollable_root(self) -> ttk.Frame:
        container = ttk.Frame(self.root)
        container.pack(fill=BOTH, expand=True)

        self.main_canvas = Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=self.main_canvas.yview)
        self.main_canvas.configure(yscrollcommand=scrollbar.set)

        self.main_canvas.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

        root_frame = ttk.Frame(self.main_canvas, padding=12)
        self.main_canvas_window = self.main_canvas.create_window((0, 0), window=root_frame, anchor="nw")

        root_frame.bind(
            "<Configure>",
            lambda _event: self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all")),
        )
        self.main_canvas.bind(
            "<Configure>",
            lambda event: self.main_canvas.itemconfigure(self.main_canvas_window, width=event.width),
        )
        self.root.bind_all("<MouseWheel>", self.on_mousewheel)
        self.root.bind_all("<Button-4>", lambda _event: self.main_canvas.yview_scroll(-1, "units"))
        self.root.bind_all("<Button-5>", lambda _event: self.main_canvas.yview_scroll(1, "units"))
        return root_frame

    def on_mousewheel(self, event) -> None:
        if event.delta:
            self.main_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def path_row(self, parent, label: str, var: StringVar, command) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=X, pady=3)
        ttk.Label(row, text=label, width=12).pack(side=LEFT)
        ttk.Entry(row, textvariable=var).pack(side=LEFT, fill=X, expand=True, padx=6)
        ttk.Button(row, text="Browse", command=command).pack(side=RIGHT)

    def add_direction_image(self, parent) -> None:
        if not DIRECTION_IMAGE_FILE.is_file():
            return
        try:
            source = PhotoImage(file=str(DIRECTION_IMAGE_FILE))
            self.direction_image = source.subsample(4, 4)
            self.direction_image_source = source
        except TclError:
            return
        ttk.Label(parent, image=self.direction_image).grid(row=0, column=3, rowspan=4, padx=(16, 0), sticky="e")

    def choose_model(self) -> None:
        path = filedialog.askopenfilename(title="Select Abaqus model", filetypes=[("Abaqus INP", "*.inp"), ("All files", "*.*")])
        if path:
            self.model_path.set(path)

    def choose_output(self) -> None:
        path = filedialog.askdirectory(title="Select output root")
        if path:
            self.output_root.set(path)

    def log(self, message: str) -> None:
        self.log_text.insert("", END, values=(message,))
        children = self.log_text.get_children()
        self.log_text.see(children[-1])

    def update_progress(self, current: int, total: int, message: str) -> None:
        self.progress_bar["maximum"] = max(total, 1)
        self.progress_bar["value"] = current
        self.progress_var.set(message)
        self.root.update_idletasks()

    def standards(self) -> list[dict]:
        return self.config_data.get(self.current_standards_key(), [])

    def current_standards_key(self) -> str:
        return PACKAGE_DROP_STANDARDS_KEY if self.case_type.get() == CASE_TYPE_PACKAGE_DROP else "standards"

    def current_directions(self) -> dict:
        if self.case_type.get() == CASE_TYPE_PACKAGE_DROP:
            return self.config_data.get(PACKAGE_DROP_DIRECTIONS_KEY, DEFAULT_PACKAGE_DROP_DIRECTIONS)
        return self.config_data.get("directions", DEFAULT_DIRECTIONS)

    def default_advanced_for_case_type(self) -> dict:
        if self.case_type.get() == CASE_TYPE_PACKAGE_DROP:
            return self.config_data.get(PACKAGE_DROP_ADVANCED_KEY, DEFAULT_PACKAGE_DROP_ADVANCED)
        return self.config_data.get("advanced_defaults", DEFAULT_ADVANCED)

    def current_standard(self) -> dict | None:
        for standard in self.standards():
            if standard.get("name") == self.standard_name.get():
                return standard
        return self.standards()[0] if self.standards() else None

    def current_weight(self) -> dict | None:
        standard = self.current_standard()
        if not standard:
            return None
        for weight in standard.get("weight_classes", []):
            if weight.get("name") == self.weight_name.get():
                return weight
        weights = standard.get("weight_classes", [])
        return weights[0] if weights else None

    def selected_directions(self) -> list[tuple[str, dict]]:
        directions = self.current_directions()
        selected = []
        for key, var in self.direction_vars.items():
            if var.get() and key in directions:
                selected.append((key, directions[key]))
        return selected

    def selected_direction_keys(self) -> list[str]:
        return [key for key, var in self.direction_vars.items() if var.get()]

    def set_names_text(self, widget: Text, names: list[str]) -> None:
        if names:
            widget.insert("1.0", "\n".join(names))

    def contact_surface_names(self) -> list[str]:
        return parse_output_names(self.contact_surface_text.get("1.0", END))

    def section_names(self) -> list[str]:
        return parse_output_names(self.section_text.get("1.0", END))

    def save_last_run_state(
        self,
        advanced: dict,
        contact_surface_names: list[str],
        section_names: list[str],
    ) -> None:
        if self.case_type.get() == CASE_TYPE_PACKAGE_DROP:
            self.config_data[PACKAGE_DROP_ADVANCED_KEY] = dict(advanced)
        else:
            self.config_data["advanced_defaults"] = dict(advanced)
        self.config_data[LAST_RUN_KEY] = {
            "case_type": self.case_type.get(),
            "model_path": self.model_path.get(),
            "output_root": self.output_root.get(),
            "standard": self.standard_name.get(),
            "weight": self.weight_name.get(),
            "directions": self.selected_direction_keys(),
            "conflict_strategy": self.conflict_strategy.get(),
            "submit_after_generate": bool(self.submit_after_generate.get()),
            "rewrite_boundary_file": bool(self.rewrite_boundary_file.get()),
            "contact_surface_names": contact_surface_names,
            "section_names": section_names,
            "advanced": dict(advanced),
        }
        save_config(self.config_data)

    def reload_config(self) -> None:
        self.config_data = ensure_config()
        standard_names = [standard.get("name", "") for standard in self.standards()]
        self.standard_combo["values"] = standard_names
        if standard_names and self.standard_name.get() not in standard_names:
            self.standard_name.set(standard_names[0])
        self.on_standard_change()

    def on_case_type_change(self) -> None:
        defaults = self.default_advanced_for_case_type()
        for key, fallback in DEFAULT_ADVANCED.items():
            self.advanced_vars[key].set(str(defaults.get(key, fallback)))
        self.standard_name.set("")
        self.weight_name.set("")
        self.reload_config()

    def on_standard_change(self) -> None:
        standard = self.current_standard()
        weight_names = [weight.get("name", "") for weight in standard.get("weight_classes", [])] if standard else []
        self.weight_combo["values"] = weight_names
        if weight_names and self.weight_name.get() not in weight_names:
            self.weight_name.set(weight_names[0])
        elif not weight_names:
            self.weight_name.set("")

    def advanced(self) -> dict:
        values = {key: var.get().strip() for key, var in self.advanced_vars.items()}
        as_float(values["friction"], "friction")
        as_float(values["analysis_time"], "analysis_time")
        as_float(values["mass_scaling_dt"], "mass_scaling_dt")
        as_int(values["field_output_interval"], "field output interval")
        as_float(values["gravity"], "gravity")
        as_int(values["cpus"], "CPUs")
        return values

    def specs(self) -> list[CaseSpec]:
        weight = self.current_weight()
        if not weight:
            return []
        return [make_case_spec(weight, key, direction) for key, direction in self.selected_directions()]

    def open_standards_editor(self) -> None:
        StandardsEditor(self)

    def generate_cases(self) -> None:
        try:
            self.generate_button.configure(state="disabled")
            self.update_progress(0, 1, "Preparing...")
            advanced = self.advanced()
            contact_surface_names = self.contact_surface_names()
            section_names = self.section_names()
            specs = self.specs()
            if not specs:
                self.update_progress(0, 1, "Ready")
                messagebox.showwarning("No cases", "Select at least one direction and one weight class.")
                return
            model = Path(self.model_path.get())
            output = Path(self.output_root.get())
            if not model.is_file():
                self.update_progress(0, 1, "Model missing")
                messagebox.showerror("Model missing", f"Model file not found:\n{model}")
                return
            if self.submit_after_generate.get() and not messagebox.askyesno("Submit", "Generate cases and submit Abaqus jobs?"):
                self.update_progress(0, len(specs), "Cancelled")
                return
            self.update_progress(0, len(specs), f"Generating 0/{len(specs)}")
            case_dirs: list[Path] = []
            for index, spec in enumerate(specs, start=1):
                self.update_progress(index - 1, len(specs), f"Generating {index}/{len(specs)}")
                case_dir = generate_case(
                    model,
                    output,
                    spec,
                    advanced,
                    case_type=self.case_type.get(),
                    conflict_strategy=self.conflict_strategy.get(),
                    rewrite_boundary_file=self.rewrite_boundary_file.get(),
                    contact_surface_names=contact_surface_names,
                    section_names=section_names,
                )
                case_dirs.append(case_dir)
                self.log(f"Generated: {case_dir}")
                self.update_progress(index, len(specs), f"Generated {index}/{len(specs)}")
            submit_path = None
            if len(specs) > 1:
                submit_path = write_multi_task_bat(output, case_dirs, specs)
                self.log(f"Generated multi-task: {submit_path}")
            elif case_dirs:
                submit_path = case_dirs[0] / f"{specs[0].job_name}.bat"
            if self.submit_after_generate.get() and submit_path:
                subprocess.Popen(["cmd", "/c", str(submit_path.name)], cwd=str(submit_path.parent))
                self.log(f"Submitted: {submit_path}")
            self.save_last_run_state(advanced, contact_surface_names, section_names)
            self.update_progress(len(specs), len(specs), f"Done: {len(specs)} case(s)")
            messagebox.showinfo("Done", f"Generated {len(specs)} case(s).")
        except Exception as exc:
            self.update_progress(0, 1, "Error")
            messagebox.showerror("Error", str(exc))
            self.log(f"Error: {exc}")
        finally:
            self.generate_button.configure(state="normal")

    def run(self) -> None:
        self.root.mainloop()


def self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        model = temp / "tiny_model.inp"
        model.write_text("*NODE\n1,0,0,0\n", encoding="utf-8")
        output = temp / "out"
        cfg = ensure_config()
        weight = cfg["standards"][0]["weight_classes"][0]
        direction = cfg["directions"]["up"]
        spec = make_case_spec(weight, "up", direction)
        case_dir = generate_case(model, output, spec, DEFAULT_ADVANCED, conflict_strategy="error")
        assert (case_dir / MODEL_COPY_NAME).is_file()
        assert (case_dir / f"{spec.job_name}.inp").is_file()
        assert (case_dir / f"{spec.job_name}.bat").is_file()
        bat_text = (case_dir / f"{spec.job_name}.bat").read_text(encoding="utf-8")
        assert bat_text.startswith('cd /d "%~dp0"\n')
        assert f"call abq2021 job={spec.job_name} cpus=8 int" in bat_text
        text = (case_dir / f"{spec.job_name}.inp").read_text(encoding="utf-8")
        assert all(line.strip() for line in text.splitlines())
        assert "*INCLUDE,INPUT=SHOCK_Model.inp" in text
        assert f"ALL_Nset,2,{format_num(spec.velocity)}" in text
        assert "Nset_SHOCK_BC, 2, 2, -9810." in text
        assert "ALL_Element, GRAV, 9810., 0., 1., 0." in text
        assert f"0.0001,              {format_num(spec.acceleration)}" in text
        assert "0.0111,              " in text
        assert "0.0112,               0.," in text
        assert "*CONTACT OUTPUT" not in text
        assert "*INTEGRATED OUTPUT" not in text
        ten_one_ms_spec = make_case_spec(
            {"name": "15_30kg", "job_prefix": "ByteDance_15_30kg_shock", "velocity": 3962.0, "acceleration": 40.0, "shock_time_ms": 10.1},
            "up",
            cfg["directions"]["up"],
        )
        nine_one_ms_spec = make_case_spec(
            {"name": "40_45kg", "job_prefix": "ByteDance_40_45kg_shock", "velocity": 3132.0, "acceleration": 35.0, "shock_time_ms": 9.1},
            "up",
            cfg["directions"]["up"],
        )
        ten_one_ms_text = render_inp(ten_one_ms_spec, DEFAULT_ADVANCED)
        nine_one_ms_text = render_inp(nine_one_ms_spec, DEFAULT_ADVANCED)
        assert "0.0102,              40.," in ten_one_ms_text
        assert "0.0103,               0.," in ten_one_ms_text
        assert "0.0092,              35.," in nine_one_ms_text
        assert "0.0093,               0.," in nine_one_ms_text
        left_spec = make_case_spec(weight, "left", {"label": "Left", "axis": 1, "sign": 1})
        right_spec = make_case_spec(weight, "right", {"label": "Right", "axis": 1, "sign": -1})
        back_spec = make_case_spec(weight, "back", {"label": "Back", "axis": 3, "sign": 1})
        front_spec = make_case_spec(weight, "front", {"label": "Front", "axis": 3, "sign": -1})
        down_spec = make_case_spec(weight, "down", {"label": "Down", "axis": 2, "sign": -1})
        left_text = render_inp(left_spec, DEFAULT_ADVANCED)
        right_text = render_inp(right_spec, DEFAULT_ADVANCED)
        back_text = render_inp(back_spec, DEFAULT_ADVANCED)
        front_text = render_inp(front_spec, DEFAULT_ADVANCED)
        down_text = render_inp(down_spec, DEFAULT_ADVANCED)
        assert f"ALL_Nset,1,{format_num(left_spec.velocity)}" in left_text
        assert "ALL_Element, GRAV, 9810., 1., 0., 0." in left_text
        assert f"ALL_Nset,1,{format_num(-right_spec.velocity)}" in right_text
        assert "ALL_Element, GRAV, 9810., -1., 0., 0." in right_text
        assert f"ALL_Nset,3,{format_num(back_spec.velocity)}" in back_text
        assert "ALL_Element, GRAV, 9810., 0., 0., 1." in back_text
        assert f"ALL_Nset,3,{format_num(-front_spec.velocity)}" in front_text
        assert "ALL_Element, GRAV, 9810., 0., 0., -1." in front_text
        assert f"ALL_Nset,2,{format_num(-down_spec.velocity)}" in down_text
        assert "ALL_Element, GRAV, 9810., 0., -1., 0." in down_text
        output_text = render_inp(spec, DEFAULT_ADVANCED, ["Pin_A", "Pin_B"], ["Sec_A"])
        assert all(line.strip() for line in output_text.splitlines())
        assert '*CONTACT OUTPUT, SURFACE = "Pin_A"' in output_text
        assert '*CONTACT OUTPUT, SURFACE = "Pin_B"' in output_text
        assert "CFN," in output_text
        assert '*OUTPUT, HISTORY, NAME ="Sec_A", TIME INTERVAL = 0.015e-03' in output_text
        assert '*INTEGRATED OUTPUT, SECTION ="Sec_A"' in output_text
        assert parse_output_names('Pin_A, Pin_B\n"Pin_A"; Sec_A') == ["Pin_A", "Pin_B", "Sec_A"]
        drop_weight = {"name": "40kg", "job_prefix": "Ali_40kg_Package_Drop", "velocity": 3834.0}
        drop_direction = {"label": "Back", "axis": 3, "sign": -1}
        drop_spec = make_case_spec(drop_weight, "back", drop_direction)
        drop_text = render_package_drop_inp(drop_spec, DEFAULT_PACKAGE_DROP_ADVANCED)
        assert all(line.strip() for line in drop_text.splitlines())
        assert "*AMPLITUDE, NAME =Curve_Grav, DEFINITION = TABULAR" in drop_text
        assert "0.025     ,1.0" in drop_text
        assert "ALL_Nset,3,-3834." in drop_text
        assert "ALL_Element,GRAV,9810.,0.,0.,-1." in drop_text
        assert "SPC_Rack_Shock,1,6,0" in drop_text
        assert "*CONTACT OUTPUT\nCFORCE,CSTATUS" in drop_text
        drop_case_dir = generate_case(
            model,
            output,
            drop_spec,
            DEFAULT_PACKAGE_DROP_ADVANCED,
            case_type=CASE_TYPE_PACKAGE_DROP,
            conflict_strategy="rename",
        )
        assert (drop_case_dir / MODEL_COPY_NAME).read_text(encoding="utf-8") == model.read_text(encoding="utf-8")
        boundary_file = case_dir / f"{spec.job_name}.inp"
        boundary_file.write_text("preserve me\n", encoding="utf-8")
        generate_case(
            model,
            output,
            spec,
            DEFAULT_ADVANCED,
            conflict_strategy="overwrite",
            rewrite_boundary_file=False,
        )
        assert boundary_file.read_text(encoding="utf-8") == "preserve me\n"
        multi_specs = [
            make_case_spec(weight, "up", cfg["directions"]["up"]),
            make_case_spec(weight, "down", cfg["directions"]["down"]),
        ]
        multi_dirs = [
            generate_case(model, output, multi_spec, DEFAULT_ADVANCED, conflict_strategy="overwrite")
            for multi_spec in multi_specs
        ]
        multi_bat = write_multi_task_bat(output, multi_dirs, multi_specs)
        assert multi_bat.name == f"{common_job_prefix(multi_specs)}_up_down.bat"
        assert multi_bat.parent == output
        assert multi_bat.read_text(encoding="utf-8") == (
            f'call "{multi_dirs[0].name}\\{multi_specs[0].job_name}.bat"\n'
            f'call "{multi_dirs[1].name}\\{multi_specs[1].job_name}.bat"\n'
        )

        component_model = temp / "component_model.inp"
        component_model.write_text(
            """*Heading
*Node
1,0,0,0
2,1,0,0
3,1,1,0
4,0,1,0
5,0,0,1
6,1,0,1
7,1,1,1
8,0,1,1
11,0,0,0
12,1,0,0
13,1,1,0
14,0,1,0
15,0,0,1
16,1,0,1
17,1,1,1
18,0,1,1
21,0,0,0
22,1,0,0
23,1,1,0
24,0,1,0
25,0,0,1
26,1,0,1
27,1,1,1
28,0,1,1
*Element, type=C3D8I, elset=LR_3D_WOOD
101,1,2,3,4,5,6,7,8
*Element, type=C3D8I, elset=UD_3D_WOOD
201,11,12,13,14,15,16,17,18
*Element, type=C3D8I, elset=FB_3D_WOOD
301,21,22,23,24,25,26,27,28
*Nset, nset=LR_3D_WOOD
1,2,3,4,5,6,7,8
*Elset, elset=FB_3D_WOOD
301
*Surface, name=LR_3D_WOOD_SURF, type=ELEMENT
101, S1
*End Part
""",
            encoding="utf-8",
        )
        up_text = build_direction_model_text(component_model, "up")
        assert "UD_3D_WOOD" in up_text
        assert "LR_3D_WOOD" not in up_text
        assert "FB_3D_WOOD" not in up_text
        assert "\n1,0,0,0" not in up_text
        assert "\n21,0,0,0" not in up_text
        assert "\n11,0,0,0" in up_text

        hw_model = temp / "hw_component_model.inp"
        hw_model.write_text(
            """*Node
1,0,0,0
2,1,0,0
3,1,1,0
4,0,1,0
5,0,0,1
6,1,0,1
7,1,1,1
8,0,1,1
11,0,0,0
12,1,0,0
13,1,1,0
14,0,1,0
15,0,0,1
16,1,0,1
17,1,1,1
18,0,1,1
21,0,0,0
22,1,0,0
23,1,1,0
24,0,1,0
25,0,0,1
26,1,0,1
27,1,1,1
28,0,1,1
**HW_COMPONENT     ID=1     NAME=UD_3D_WOOD     PROPERTY=UP_DOWN
*Element, type=C3D8I, elset=UP_DOWN
201,11,12,13,14,15,16,17,18
**HW_COMPONENT     ID=2     NAME=FB_3D_WOOD     PROPERTY=UP_DOWN
*Element, type=C3D8I, elset=UP_DOWN
301,21,22,23,24,25,26,27,28
**HW_COMPONENT     ID=3     NAME=LR_3D_WOOD     PROPERTY=UP_DOWN
*Element, type=C3D8I, elset=UP_DOWN
101,1,2,3,4,5,6,7,8
*Nset, nset=ALL_Nset
1,2,3,4,5,6,7,8,11,12,13,14,15,16,17,18,21,22,23,24,25,26,27,28
*Elset, elset=ALL_Element
101,201,301
*Solid Section, elset=UP_DOWN, material=Wood
""",
            encoding="utf-8",
        )
        hw_up_text = build_direction_model_text(hw_model, "up")
        assert "UD_3D_WOOD" in hw_up_text
        assert "FB_3D_WOOD" not in hw_up_text
        assert "LR_3D_WOOD" not in hw_up_text
        assert "201" in hw_up_text
        assert "101" not in hw_up_text
        assert "301" not in hw_up_text
        assert "\n11,0,0,0" in hw_up_text
        assert "\n1,0,0,0" not in hw_up_text
        assert "\n21,0,0,0" not in hw_up_text

        package_model = temp / "package_component_model.inp"
        package_model.write_text(
            """*Node
1,0,0,0
2,1,0,0
3,1,1,0
4,0,1,0
5,0,0,1
6,1,0,1
7,1,1,1
8,0,1,1
11,0,0,0
12,1,0,0
13,1,1,0
14,0,1,0
15,0,0,1
16,1,0,1
17,1,1,1
18,0,1,1
21,0,0,0
22,1,0,0
23,1,1,0
24,0,1,0
25,0,0,1
26,1,0,1
27,1,1,1
28,0,1,1
**HW_COMPONENT     ID=1     NAME=UP_2D_TT0p1_STEEL
*Element, type=S4R, elset=DROP_STEEL
201,11,12,13,14
**HW_COMPONENT     ID=2     NAME=DOWN_2D_TT0p1_STEEL
*Element, type=S4, elset=DROP_STEEL
301,21,22,23,24
**HW_COMPONENT     ID=3     NAME=LEFT_2D_TT0p1_STEEL
*Element, type=S4, elset=DROP_STEEL
101,1,2,3,4
*Nset, nset=ALL_Nset
1,2,3,4,5,6,7,8,11,12,13,14,15,16,17,18,21,22,23,24,25,26,27,28
*Elset, elset=ALL_Element
101,201,301
""",
            encoding="utf-8",
        )
        package_up_text = build_package_drop_model_text(package_model, "up")
        assert "UP_2D_TT0p1_STEEL" in package_up_text
        assert "DOWN_2D_TT0p1_STEEL" not in package_up_text
        assert "LEFT_2D_TT0p1_STEEL" not in package_up_text
        assert "201" in package_up_text
        assert "101" not in package_up_text
        assert "301" not in package_up_text
        assert "\n11,0,0,0" in package_up_text
        assert "\n1,0,0,0" not in package_up_text
        assert "\n21,0,0,0" not in package_up_text
    print("self-test passed")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        ShockGeneratorApp().run()
