"""
lora_merge.py — production LoRA fusion via mergekit.

The `fusion_engine.py` SLERP code demonstrates the math, but the real,
production way to merge adapters is mergekit (https://github.com/arcee-ai/mergekit)
— it's battle-tested, supports TIES / DARE / SLERP / task-arithmetic, and
handles base-model alignment, tokenizer reconciliation, and dtype correctly.

This module turns a Fusion Event into a real mergekit run:

  1. Validate both adapters target the SAME base model (you cannot merge
     adapters trained on different bases — that's the honest hard constraint).
  2. Emit a mergekit YAML config with capital-weighted blend weights derived
     from the binding-energy share (who paid more weighs more).
  3. Invoke `mergekit-yaml` as a subprocess.
  4. (Optional) run an eval harness so you KNOW whether the merge helped,
     instead of assuming it did.

Honest execution note: steps 3-4 require the base model + adapter weights on
disk and compute (CPU works for small models; GPU for real ones). This module
generates the real config and drives the real tool; it does not fake a merge.
If mergekit isn't installed, `run_merge` raises with the install command.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml  # pyyaml


@dataclass
class AdapterSpec:
    name: str
    path: str            # local path or HF repo id of the LoRA adapter
    base_model: str      # the base model this adapter was trained on


class IncompatibleBaseError(Exception):
    """Raised when two adapters do not share a base model."""


def binding_energy_weights(rlusd_a: float, rlusd_b: float) -> tuple[float, float]:
    total = rlusd_a + rlusd_b
    if total <= 0:
        return 0.5, 0.5
    return rlusd_a / total, rlusd_b / total


def build_merge_config(
    a: AdapterSpec,
    b: AdapterSpec,
    rlusd_a: float,
    rlusd_b: float,
    method: str = "ties",
    density: float = 0.5,
) -> dict:
    """Produce a real mergekit config dict for a capital-weighted adapter merge.

    `method`: ties | dare_ties | linear | slerp. TIES is a good default for
    combining task-specific adapters with minimal interference.
    """
    if a.base_model != b.base_model:
        raise IncompatibleBaseError(
            f"cannot fuse adapters on different bases: "
            f"{a.base_model!r} vs {b.base_model!r}. Re-base one first."
        )
    wa, wb = binding_energy_weights(rlusd_a, rlusd_b)
    return {
        "base_model": a.base_model,
        "merge_method": method,
        "dtype": "bfloat16",
        "models": [
            {"model": a.path, "parameters": {"weight": round(wa, 4), "density": density}},
            {"model": b.path, "parameters": {"weight": round(wb, 4), "density": density}},
        ],
        # TIES/DARE need a base to compute task vectors against.
        "parameters": {"normalize": True, "int8_mask": True},
    }


def write_config(config: dict, out_dir: str) -> str:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cfg_path = out / "merge_config.yaml"
    cfg_path.write_text(yaml.safe_dump(config, sort_keys=False))
    return str(cfg_path)


def run_merge(config: dict, out_dir: str, lazy_unpickle: bool = True,
              extra_args: Optional[list[str]] = None) -> str:
    """Run a real mergekit merge. Returns the output model directory.

    Requires `mergekit` installed: pip install mergekit
    """
    if shutil.which("mergekit-yaml") is None:
        raise RuntimeError(
            "mergekit not installed. Install with:  pip install mergekit\n"
            "Then this will run the real merge."
        )
    cfg_path = write_config(config, out_dir)
    model_out = str(Path(out_dir) / "merged")
    cmd = ["mergekit-yaml", cfg_path, model_out, "--copy-tokenizer"]
    if lazy_unpickle:
        cmd.append("--lazy-unpickle")
    if extra_args:
        cmd.extend(extra_args)
    subprocess.run(cmd, check=True)
    return model_out


@dataclass
class MergeEval:
    metric: str
    base_score: float
    merged_score: float

    @property
    def delta(self) -> float:
        return self.merged_score - self.base_score

    @property
    def helped(self) -> bool:
        return self.delta > 0


def evaluate_merge(eval_fn, base_model_dir: str, merged_dir: str,
                   metric: str = "task_accuracy") -> MergeEval:
    """Run a caller-supplied eval on base vs merged so a fusion is only kept if
    it measurably helped. `eval_fn(model_dir) -> float`. This is the honesty
    gate: a merge that doesn't improve the metric should be discarded, not
    shipped as a 'Blue Giant'."""
    base = float(eval_fn(base_model_dir))
    merged = float(eval_fn(merged_dir))
    return MergeEval(metric=metric, base_score=base, merged_score=merged)
