#!/usr/bin/env python3

"""Shared JSON serialization for dice runtime values."""

from __future__ import annotations

import json

from diceengine import (
    Distributions,
    Distribution,
    FiniteMeasure,
    RecordValue,
    TupleValue,
)


def is_numeric(value):
    return isinstance(value, (int, float))


def round_numeric(value, roundlevel):
    if roundlevel and isinstance(value, float):
        return round(value, roundlevel)
    return value


def ordered_labels(values):
    def sort_key(value):
        if isinstance(value, (int, float)):
            return (0, value)
        if isinstance(value, str):
            return (1, value)
        if isinstance(value, TupleValue):
            return (2, str(value))
        if isinstance(value, RecordValue):
            return (3, str(value))
        return (4, str(value))

    return list(sorted(values, key=sort_key))


def serialize_embedded_value(value, roundlevel=0, probability_mode="raw"):
    if isinstance(value, TupleValue):
        return {
            "type": "tuple",
            "items": [
                serialize_embedded_value(item, roundlevel, probability_mode=probability_mode)
                for item in value.items
            ],
        }
    if isinstance(value, RecordValue):
        return {
            "type": "record",
            "entries": [
                {
                    "key_kind": "integer" if isinstance(key, int) else "identifier",
                    "key": key,
                    "value": serialize_embedded_value(
                        entry_value,
                        roundlevel,
                        probability_mode=probability_mode,
                    ),
                }
                for key, entry_value in value.items()
            ],
        }
    if isinstance(value, Distribution):
        return {
            "type": "distribution",
            "distribution": serialize_distribution(
                value,
                roundlevel,
                probability_mode=probability_mode,
            ),
        }
    if isinstance(value, FiniteMeasure):
        return {
            "type": "measure",
            "measure": serialize_measure(value, roundlevel),
        }
    if isinstance(value, str):
        return value
    if is_numeric(value):
        return round_numeric(value, roundlevel)
    return str(value)


def resolve_probability_mode(probability_mode=None, json_output=False):
    if probability_mode is not None:
        return probability_mode
    return "raw" if json_output else "percent"


def serialize_distribution(distrib, roundlevel=0, probability_mode="raw"):
    scale = 100.0 if probability_mode == "percent" else 1.0
    entries = []
    for outcome in ordered_labels(distrib.keys()):
        entries.append(
            {
                "outcome": serialize_embedded_value(
                    outcome,
                    roundlevel,
                    probability_mode=probability_mode,
                ),
                "probability": round_numeric(distrib[outcome] * scale, roundlevel),
            }
        )
    return entries


def serialize_measure(measure, roundlevel=0):
    entries = []
    for outcome in ordered_labels(measure.keys()):
        entries.append(
            {
                "outcome": serialize_embedded_value(outcome, roundlevel),
                "weight": round_numeric(measure[outcome], roundlevel),
            }
        )
    return entries


def serialize_result(result, roundlevel=0, probability_mode="raw"):
    if isinstance(result, Distributions):
        distribution_only = all(isinstance(distrib, Distribution) for distrib in result.cells.values())
        axes = [
            {
                "key": axis.key,
                "name": axis.name if not axis.name.startswith("sweep_") else None,
                "values": [
                    serialize_embedded_value(
                        value,
                        roundlevel,
                        probability_mode=probability_mode,
                    )
                    for value in axis.values
                ],
            }
            for axis in result.axes
        ]
        cells = []
        for coordinates, distrib in result.cells.items():
            coordinate_entries = []
            for axis, value in zip(result.axes, coordinates):
                coordinate_entries.append(
                    {
                        "axis_key": axis.key,
                        "axis_name": axis.name if not axis.name.startswith("sweep_") else None,
                        "value": serialize_embedded_value(
                            value,
                            roundlevel,
                            probability_mode=probability_mode,
                        ),
                    }
                )
            if distribution_only:
                cells.append(
                    {
                        "coordinates": coordinate_entries,
                        "distribution": serialize_distribution(
                            distrib,
                            roundlevel,
                            probability_mode=probability_mode,
                        ),
                    }
                )
            else:
                cells.append(
                    {
                        "coordinates": coordinate_entries,
                        "value": (
                            {
                                "kind": "measure",
                                "measure": serialize_measure(distrib, roundlevel),
                            }
                            if isinstance(distrib, FiniteMeasure)
                            else {
                                "kind": (
                                    "scalar"
                                    if is_numeric(distrib)
                                    else "string"
                                    if isinstance(distrib, str)
                                    else "tuple"
                                    if isinstance(distrib, TupleValue)
                                    else "record"
                                    if isinstance(distrib, RecordValue)
                                    else type(distrib).__name__
                                ),
                                "value": serialize_embedded_value(
                                    distrib,
                                    roundlevel,
                                    probability_mode=probability_mode,
                                ),
                            }
                        ),
                    }
                )
        return {
            "type": "distributions" if distribution_only else "sweep",
            "axes": axes,
            "cells": cells,
        }
    if isinstance(result, Distribution):
        return {
            "type": "distribution",
            "distribution": serialize_distribution(
                result,
                roundlevel,
                probability_mode=probability_mode,
            ),
        }
    if isinstance(result, FiniteMeasure):
        return {"type": "measure", "measure": serialize_measure(result, roundlevel)}
    if isinstance(result, TupleValue):
        return serialize_embedded_value(result, roundlevel, probability_mode=probability_mode)
    if isinstance(result, RecordValue):
        return serialize_embedded_value(result, roundlevel, probability_mode=probability_mode)
    if isinstance(result, str):
        return {"type": "string", "value": result}
    if is_numeric(result):
        return {"type": "scalar", "value": round_numeric(result, roundlevel)}
    return {"type": type(result).__name__, "value": str(result)}


def format_result_json(result, roundlevel=0, probability_mode="raw"):
    return json.dumps(
        serialize_result(result, roundlevel, probability_mode=probability_mode),
        indent=2,
    )
