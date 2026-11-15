"""Install SSVEPAnalysisToolbox into the active conda env and make it work with its numpy.

The toolbox pins numpy<=1.23 and scipy<=1.13, which would downgrade (or break)
both project envs, so it is installed without its dependencies. Only the ones its
algorithm modules import are installed, with conda. Two numpy incompatibilities
in the toolbox are then patched in place:
    utils/io.py         `from numpy import object`  (removed in numpy 1.24)
    algorithms/*.py     int() of a 1-element array  (an error in numpy >= 2)

Run inside the activated env (safe to repeat):
    conda activate BrainHeroes
    python setup_ssvep_toolbox.py
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

TOOLBOX_REQUIREMENT = "SSVEPAnalysisToolbox==0.0.5"
CONDA_DEPENDENCIES = ["joblib", "scikit-learn", "h5py", "mat73"]
PATCHES = {
    "utils/io.py": [("from numpy import ndarray, object\n", "from numpy import ndarray\n")],
    "algorithms/cca.py": [("axis = 1)) for r_single", "axis = 1)[0]) for r_single")],
    "algorithms/lsframework.py": [("axis = 1)) for r_single", "axis = 1)[0]) for r_single")],
}


def install_dependencies() -> None:
    conda = os.environ.get("CONDA_EXE")
    if conda is None:
        raise RuntimeError("CONDA_EXE is not set - activate the conda env first.")
    subprocess.run([conda, "install", "-y", "--prefix", sys.prefix, "-c", "conda-forge",
                    *CONDA_DEPENDENCIES], check=True)


def install_toolbox() -> None:
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", TOOLBOX_REQUIREMENT],
                   check=True)


def toolbox_directory() -> Path:
    spec = importlib.util.find_spec("SSVEPAnalysisToolbox")
    if spec is None or spec.origin is None:
        raise RuntimeError("SSVEPAnalysisToolbox is not installed.")
    return Path(spec.origin).parent


def apply_patches(package_dir: Path) -> None:
    for relative_path, replacements in PATCHES.items():
        path = package_dir / relative_path
        text = path.read_text(encoding="utf-8")
        for old, new in replacements:
            text = text.replace(old, new)
        path.write_text(text, encoding="utf-8")
        print(f"patched {relative_path}")


def main() -> None:
    install_dependencies()
    install_toolbox()
    apply_patches(toolbox_directory())
    print("SSVEPAnalysisToolbox ready.")


if __name__ == "__main__":
    main()
