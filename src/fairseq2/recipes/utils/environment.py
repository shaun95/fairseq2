# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import annotations

import os
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Set
from random import Random
from typing import Callable, final

from typing_extensions import override


class EnvironmentSetter(ABC):
    """Sets job environment variables."""

    @abstractmethod
    def set_torch_distributed_env(self) -> None:
        """Set environment variables required to initialize ``torch.distributed``."""

    @property
    @abstractmethod
    def cluster(self) -> str:
        """The cluster type that this instance supports."""


@final
class SlurmEnvironmentSetter(EnvironmentSetter):
    """Sets job environment variables on a Slurm cluster."""

    _job_id: int

    def __init__(self) -> None:
        try:
            job_id = os.environ["SLURM_JOB_ID"]
        except KeyError:
            raise RuntimeError(
                "Slurm not detected. `SLURM_JOB_ID` environment variable cannot be found."
            ) from None

        try:
            self._job_id = int(job_id)
        except ValueError as ex:
            raise RuntimeError("Slurm job ID cannot be parsed.") from ex

    @override
    def set_torch_distributed_env(self) -> None:
        try:
            os.environ["WORLD_SIZE"] = os.environ["SLURM_NTASKS"]
            os.environ["RANK"] = os.environ["SLURM_PROCID"]

            try:
                os.environ["LOCAL_WORLD_SIZE"] = os.environ["SLURM_NTASKS_PER_NODE"]
            except KeyError:
                os.environ["LOCAL_WORLD_SIZE"] = "1"

            os.environ["LOCAL_RANK"] = os.environ["SLURM_LOCALID"]

            os.environ["MASTER_ADDR"] = self._get_master_addr()
            os.environ["MASTER_PORT"] = self._get_master_port()

            os.environ["CUDA_VISIBLE_DEVICES"] = os.environ["SLURM_LOCALID"]
        except KeyError as ex:
            raise RuntimeError(
                "Slurm job environment variables are not correctly set. If you are within an allocated job (i.e. `salloc`), make sure to run with `srun`. If you want to run without Slurm, use `--cluster none`."
            ) from ex

    def _get_master_addr(self) -> str:
        nodes = os.environ["SLURM_JOB_NODELIST"]

        result = subprocess.run(
            ["scontrol", "show", "hostnames", nodes], capture_output=True, text=True
        )

        if result.returncode == 0:
            if node_list := result.stdout.split("\n"):
                return node_list[0]

        raise RuntimeError(
            "The hostname or IP address of the Slurm node corresponding to rank 0 cannot be retrieved."
        )

    def _get_master_port(self) -> str:
        try:
            return os.environ["MASTER_PORT"]
        except KeyError:
            pass

        return str(Random(self._job_id).randint(20_000, 60_000))

    @property
    @override
    def cluster(self) -> str:
        return "slurm"


@final
class _NoneEnvironmentSetter(EnvironmentSetter):
    @override
    def set_torch_distributed_env(self) -> None:
        return

    @property
    @override
    def cluster(self) -> str:
        return "none"


class EnvironmentSetterRegistry:
    """Holds cluster type to :class:`EnvironmentSetter` mappings."""

    _factories: dict[str, Callable[[], EnvironmentSetter]]

    def __init__(self) -> None:
        self._factories = {
            "slurm": SlurmEnvironmentSetter,
            "none": _NoneEnvironmentSetter,
        }

    def get(self, cluster: str) -> EnvironmentSetter:
        """Return the :class:`EnvironmentSetter` of the specified cluster type."""
        try:
            factory = self._factories[cluster]
        except KeyError:
            raise ValueError(
                f"`cluster` must be a registered cluster name, but is '{cluster}' instead."
            ) from None

        return factory()

    def get_for_inferred_cluster(self) -> EnvironmentSetter:
        """Return the :class:`EnvironmentSetter` of the inferred cluster."""
        if "TORCHELASTIC_RUN_ID" in os.environ:  # means we are in `torchrun`.
            return self.get("none")

        for cluster, factory in self._factories.items():
            if cluster == "none":
                continue

            try:
                return factory()
            except RuntimeError:
                pass

        return self.get("none")

    def register(self, cluster: str, factory: Callable[[], EnvironmentSetter]) -> None:
        """Register a new :class:`EnvironmentSetter`.

        :param cluster:
            The cluster type.
        :param factory:
            The factory to construct an :class:`EnvironmentSetter`.
        """
        if cluster in self._factories:
            raise ValueError(
                f"`cluster` must be a unique cluster name, but '{cluster}' is already registered."
            )

        self._factories[cluster] = factory

    def names(self) -> Set[str]:
        """Return the supported cluster types."""
        return self._factories.keys()


default_env_setters = EnvironmentSetterRegistry()
