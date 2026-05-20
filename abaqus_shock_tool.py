from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from tkinter import (
    BooleanVar,
    END,
    LEFT,
    RIGHT,
    BOTH,
    X,
    Y,
    StringVar,
    Tk,
    Toplevel,
    filedialog,
    messagebox,
    simpledialog,
)
from tkinter import ttk


APP_TITLE = "Abaqus Shock Case Generator"
CONFIG_FILE = Path(__file__).with_name("shock_standards.json")
MODEL_COPY_NAME = "SHOCK_Model.inp"


DEFAULT_DIRECTIONS = {
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


DEFAULT_CONFIG = {
    "directions": DEFAULT_DIRECTIONS,
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
                }
            ],
        }
    ],
    "advanced_defaults": DEFAULT_ADVANCED,
}


CONTACT_SURFACES = [
    "Top_Cover_Pin_Left_1",
    "Top_Cover_Pin_Left_2",
    "Top_Cover_Pin_Left_3",
    "Top_Cover_Pin_Left_4",
    "Top_Cover_Pin_Left_5",
    "Top_Cover_Pin_Right_1",
    "Top_Cover_Pin_Right_2",
    "Top_Cover_Pin_Right_3",
    "Top_Cover_Pin_Right_4",
    "Top_Cover_Pin_Right_5",
    "Top_Cover_Pin_Rear_Left",
    "Top_Cover_Pin_Rear_Middle",
    "Top_Cover_Pin_Rear_Right",
    "Top_Cover_Pin_Lock_1",
    "Top_Cover_Pin_Lock_2",
]


@dataclass(frozen=True)
class CaseSpec:
    job_name: str
    direction_key: str
    direction_label: str
    axis: int
    sign: int
    velocity: float
    acceleration: float


def ensure_config(path: Path = CONFIG_FILE) -> dict:
    if not path.exists():
        save_config(DEFAULT_CONFIG, path)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    data.setdefault("directions", DEFAULT_DIRECTIONS)
    data.setdefault("standards", DEFAULT_CONFIG["standards"])
    data.setdefault("advanced_defaults", DEFAULT_ADVANCED)
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
        acceleration=as_float(weight_class.get("acceleration"), "acceleration"),
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


def render_inp(spec: CaseSpec, advanced: dict) -> str:
    analysis_time = advanced["analysis_time"]
    history_interval = advanced["history_interval"]
    friction = advanced["friction"]
    mass_dt = advanced["mass_scaling_dt"]
    field_interval = advanced["field_output_interval"]
    gravity = advanced["gravity"]
    velocity_value = spec.sign * spec.velocity
    boundary_lines = render_boundary_lines_with_base(spec, as_float(gravity, "gravity"))
    contact_outputs = "\n".join(
        f"*CONTACT OUTPUT, SURFACE = {surface}\nCFN," for surface in CONTACT_SURFACES
    )

    return f"""*INCLUDE,INPUT={MODEL_COPY_NAME}
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
0.0111,              {format_num(spec.acceleration)},
0.0112,               0.,
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
ALL_Element, GRAV, {gravity}, 0., 1., 0.
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
{contact_outputs}
****************************************************************************************************
*END STEP
"""


def render_bat(job_name: str, advanced: dict) -> str:
    command = advanced["abaqus_command"].strip() or "abq2021"
    cpus = advanced["cpus"].strip() or "8"
    return f"call {command} job={job_name} cpus={cpus} int\n"


def generate_case(
    model_path: Path,
    output_root: Path,
    spec: CaseSpec,
    advanced: dict,
    conflict_strategy: str = "error",
    submit: bool = False,
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
    shutil.copy2(model_path, case_dir / MODEL_COPY_NAME)
    (case_dir / f"{spec.job_name}.inp").write_text(render_inp(spec, advanced), encoding="utf-8")
    bat_path = case_dir / f"{spec.job_name}.bat"
    bat_path.write_text(render_bat(spec.job_name, advanced), encoding="utf-8")

    if submit:
        subprocess.Popen(["cmd", "/c", str(bat_path.name)], cwd=str(case_dir))

    return case_dir


class StandardsEditor(Toplevel):
    def __init__(self, master: "ShockGeneratorApp") -> None:
        super().__init__(master.root)
        self.master_app = master
        self.title("Standards Library")
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
            columns=("name", "prefix", "velocity", "acceleration"),
            show="headings",
            height=10,
        )
        for column, label, width in [
            ("name", "Name", 150),
            ("prefix", "Job Prefix", 180),
            ("velocity", "Velocity", 100),
            ("acceleration", "Acceleration", 110),
        ]:
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
        return self.config_data.setdefault("standards", [])

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
        )
        if acceleration is None:
            return None
        return {
            "name": name.strip(),
            "job_prefix": safe_name(prefix),
            "velocity": velocity,
            "acceleration": acceleration,
        }

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

        self.model_path = StringVar(value=str(Path("Ali_40kg_Shock_1_up") / MODEL_COPY_NAME))
        self.output_root = StringVar(value=str(Path.cwd() / "generated_cases"))
        self.standard_name = StringVar()
        self.weight_name = StringVar()
        self.submit_after_generate = BooleanVar(value=False)
        self.conflict_strategy = StringVar(value="rename")
        self.direction_vars: dict[str, BooleanVar] = {}
        self.advanced_vars = {
            key: StringVar(value=str(self.config_data.get("advanced_defaults", DEFAULT_ADVANCED).get(key, value)))
            for key, value in DEFAULT_ADVANCED.items()
        }

        self.build_ui()
        self.reload_config()

    def build_ui(self) -> None:
        root_frame = ttk.Frame(self.root, padding=12)
        root_frame.pack(fill=BOTH, expand=True)

        paths = ttk.LabelFrame(root_frame, text="Paths", padding=10)
        paths.pack(fill=X)
        self.path_row(paths, "Model file", self.model_path, self.choose_model)
        self.path_row(paths, "Output root", self.output_root, self.choose_output)

        selection = ttk.LabelFrame(root_frame, text="Case Selection", padding=10)
        selection.pack(fill=X, pady=10)
        ttk.Label(selection, text="Standard").grid(row=0, column=0, sticky="w")
        self.standard_combo = ttk.Combobox(selection, textvariable=self.standard_name, state="readonly", width=28)
        self.standard_combo.grid(row=0, column=1, sticky="ew", padx=6)
        self.standard_combo.bind("<<ComboboxSelected>>", lambda _event: self.on_standard_change())
        ttk.Button(selection, text="Edit Standards", command=self.open_standards_editor).grid(row=0, column=2, padx=6)

        ttk.Label(selection, text="Weight").grid(row=1, column=0, sticky="w", pady=6)
        self.weight_combo = ttk.Combobox(selection, textvariable=self.weight_name, state="readonly", width=28)
        self.weight_combo.grid(row=1, column=1, sticky="ew", padx=6, pady=6)
        self.weight_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_preview())

        directions_frame = ttk.Frame(selection)
        directions_frame.grid(row=2, column=1, columnspan=2, sticky="w", pady=4)
        for key in DEFAULT_DIRECTIONS:
            var = BooleanVar(value=(key == "up"))
            self.direction_vars[key] = var
            ttk.Checkbutton(
                directions_frame,
                text=DEFAULT_DIRECTIONS[key]["label"],
                variable=var,
                command=self.refresh_preview,
            ).pack(side=LEFT, padx=(0, 10))
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

        preview_frame = ttk.LabelFrame(root_frame, text="Preview", padding=10)
        preview_frame.pack(fill=BOTH, expand=True)
        self.preview = ttk.Treeview(preview_frame, columns=("folder", "direction"), show="headings", height=8)
        self.preview.heading("folder", text="Case folder / job")
        self.preview.heading("direction", text="Direction")
        self.preview.column("folder", width=520)
        self.preview.column("direction", width=120)
        self.preview.pack(fill=BOTH, expand=True)

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
        ttk.Checkbutton(actions, text="Submit after generate", variable=self.submit_after_generate).pack(side=LEFT, padx=12)
        ttk.Button(actions, text="Refresh Preview", command=self.refresh_preview).pack(side=RIGHT, padx=6)
        ttk.Button(actions, text="Generate Cases", command=self.generate_cases).pack(side=RIGHT)

        log_frame = ttk.LabelFrame(root_frame, text="Log", padding=8)
        log_frame.pack(fill=BOTH, expand=True)
        self.log_text = ttk.Treeview(log_frame, columns=("message",), show="headings", height=5)
        self.log_text.heading("message", text="Message")
        self.log_text.column("message", width=840)
        self.log_text.pack(fill=BOTH, expand=True)

    def path_row(self, parent, label: str, var: StringVar, command) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=X, pady=3)
        ttk.Label(row, text=label, width=12).pack(side=LEFT)
        ttk.Entry(row, textvariable=var).pack(side=LEFT, fill=X, expand=True, padx=6)
        ttk.Button(row, text="Browse", command=command).pack(side=RIGHT)

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

    def standards(self) -> list[dict]:
        return self.config_data.get("standards", [])

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
        directions = self.config_data.get("directions", DEFAULT_DIRECTIONS)
        selected = []
        for key, var in self.direction_vars.items():
            if var.get() and key in directions:
                selected.append((key, directions[key]))
        return selected

    def reload_config(self) -> None:
        self.config_data = ensure_config()
        standard_names = [standard.get("name", "") for standard in self.standards()]
        self.standard_combo["values"] = standard_names
        if standard_names and self.standard_name.get() not in standard_names:
            self.standard_name.set(standard_names[0])
        self.on_standard_change()

    def on_standard_change(self) -> None:
        standard = self.current_standard()
        weight_names = [weight.get("name", "") for weight in standard.get("weight_classes", [])] if standard else []
        self.weight_combo["values"] = weight_names
        if weight_names and self.weight_name.get() not in weight_names:
            self.weight_name.set(weight_names[0])
        elif not weight_names:
            self.weight_name.set("")
        self.refresh_preview()

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

    def refresh_preview(self) -> None:
        self.preview.delete(*self.preview.get_children())
        output_root = Path(self.output_root.get())
        for spec in self.specs():
            self.preview.insert("", END, values=(str(output_root / spec.job_name), spec.direction_label))

    def open_standards_editor(self) -> None:
        StandardsEditor(self)

    def generate_cases(self) -> None:
        try:
            advanced = self.advanced()
            specs = self.specs()
            if not specs:
                messagebox.showwarning("No cases", "Select at least one direction and one weight class.")
                return
            model = Path(self.model_path.get())
            output = Path(self.output_root.get())
            if not model.is_file():
                messagebox.showerror("Model missing", f"Model file not found:\n{model}")
                return
            if self.submit_after_generate.get() and not messagebox.askyesno("Submit", "Generate cases and submit Abaqus jobs?"):
                return
            for spec in specs:
                case_dir = generate_case(
                    model,
                    output,
                    spec,
                    advanced,
                    conflict_strategy=self.conflict_strategy.get(),
                    submit=self.submit_after_generate.get(),
                )
                self.log(f"Generated: {case_dir}")
            messagebox.showinfo("Done", f"Generated {len(specs)} case(s).")
        except Exception as exc:
            messagebox.showerror("Error", str(exc))
            self.log(f"Error: {exc}")

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
        text = (case_dir / f"{spec.job_name}.inp").read_text(encoding="utf-8")
        assert "*INCLUDE,INPUT=SHOCK_Model.inp" in text
        assert "ALL_Nset,2,4315." in text
        assert "Nset_SHOCK_BC, 2, 2, -9810." in text
        assert "0.0001,              40." in text
    print("self-test passed")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        ShockGeneratorApp().run()
