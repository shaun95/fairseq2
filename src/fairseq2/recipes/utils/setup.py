# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from typing import Dict

import torch

from fairseq2.device import determine_default_device
from fairseq2.gang import Gang, setup_default_gang, setup_parallel_gangs
from fairseq2.logging import LogWriter
from fairseq2.recipes.utils.log import log_environment_info


def setup_root_gang(log: LogWriter, *, monitored: bool = False) -> Gang:
    """Set up the root gang.

    :param log:
        The log to write to.
    :param monitored:
        If ``True``,  puts a monitored barrier before every collective call.
    """
    device = determine_default_device()

    log_environment_info(log, device)

    # In case we run on Ampere or later, use TF32.
    torch.set_float32_matmul_precision("high")

    log.info("Initializing the root gang.")

    gang = setup_default_gang(monitored=monitored)

    log.info("Root gang initialized.")

    return gang


def setup_gangs(
    log: LogWriter, *, tp_size: int = 1, monitored: bool = False
) -> Dict[str, Gang]:
    """Set up the root, data, and tensor parallel gangs.

    :param log:
        The log to write to.
    :param tp_size:
        The size of tensor parallel gangs.
    :param monitored:
        If ``True``,  puts a monitored barrier before every collective call.
    """
    root_gang = setup_root_gang(log, monitored=monitored)

    log.info("Initializing data and tensor parallel gangs.")

    try:
        gangs = setup_parallel_gangs(root_gang, tp_size=tp_size)
    except ValueError as ex:
        raise RuntimeError(
            f"The size of the root gang ({root_gang.size}) is not divisible by `tp_size` ({tp_size})."
        ) from ex

    log.info("Data and tensor parallel gangs initialized.")

    return gangs