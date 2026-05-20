# Abaqus Shock Case Generator

Windows Tkinter tool for generating Abaqus shock-condition folders from a shared model and editable standards.

## Run

Use `run_tool.bat`, or run:

```powershell
python abaqus_shock_tool.py
```

If `python` is not in `PATH`, `run_tool.bat` also tries the Codex bundled Python runtime when it exists. Otherwise, run the script with the full path to your Python executable.

## Workflow

1. Select the source model `.inp`.
2. Select an output root folder.
3. Choose a shock standard and weight class.
4. Check one or more directions.
5. Review the preview and click `Generate Cases`.

Each selected condition creates a separate folder:

```text
<output_root>/<job_name>/
  SHOCK_Model.inp
  <job_name>.inp
  <job_name>.bat
```

The model is copied into every case folder, and generated `.inp` files include it through:

```text
*INCLUDE,INPUT=SHOCK_Model.inp
```

## Standards

Click `Edit Standards` to add, edit, or delete standards and weight classes. The library is saved in `shock_standards.json`.

Each weight class defines:

- `name`
- `job_prefix`
- `velocity`
- `acceleration` shock acceleration / amplitude peak, such as `40.0` for the reference case

Direction mapping is stored in `shock_standards.json` under `directions`. By default, `up/down` use Abaqus DOF 2, `left/right` use DOF 1, and `front/back` use DOF 3. Initial velocity follows the selected direction; the acceleration amplitude is written into `*Amplitude`, while the boundary coefficient uses the gravity base value with the opposite sign, matching the reference `up` case.

## Verification

Run a logic self-test without opening the UI:

```powershell
python abaqus_shock_tool.py --self-test
```
