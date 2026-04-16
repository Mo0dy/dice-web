#!/usr/bin/env python3

"""Browser-safe viewer shim for dice-web."""

from __future__ import annotations

from dataclasses import dataclass

from diceengine import RenderConfig, _coerce_to_distributions


@dataclass(frozen=True)
class RenderSpec:
    kind: str
    x_label: str
    y_label: str
    series_labels: tuple = ()


@dataclass(frozen=True)
class RenderOutcome:
    spec: RenderSpec
    output_path: str | None = None


_RENDER_PAYLOADS = []


def reset_render_log():
    _RENDER_PAYLOADS.clear()


def get_render_log():
    return list(_RENDER_PAYLOADS)


def wait_for_rendered_figures(render_config=None):
    return None


def _fallback_axis_name(axis, index):
    if axis.name and not axis.name.startswith("sweep_"):
        return axis.name
    return "Sweep {}".format(index + 1)


def _ordered_values(values):
    try:
        return tuple(sorted(values))
    except TypeError:
        return tuple(values)


def _is_scalar_distribution(distrib):
    items = list(distrib.items())
    return (
        len(items) == 1
        and items[0][1] == 1
        and isinstance(items[0][0], (int, float))
    )


def _scalar_value(distrib):
    return next(iter(distrib.keys()))


def _all_scalar(result):
    return all(_is_scalar_distribution(distrib) for distrib in result.cells.values())


def _common_axis_name(results):
    if not results:
        return "Sweep 1"
    names = []
    for result in results:
        axis = result.axes[0]
        names.append(_fallback_axis_name(axis, 0))
    first = names[0]
    if all(name == first for name in names):
        return first
    raise Exception("Viewer exception: render comparison requires matching sweep axis names")


def _validate_same_axis_values(results):
    values = results[0].axes[0].values
    for result in results[1:]:
        if result.axes[0].values != values:
            raise Exception("Viewer exception: render comparison requires matching sweep axis values")


def _validate_outcome_domains(results):
    outcome_types = set()
    for result in results:
        for outcome in result.only_distribution().keys():
            outcome_types.add(isinstance(outcome, (int, float)))
    if len(outcome_types) > 1:
        raise Exception("Viewer exception: render comparison requires consistent outcome domains")


def build_render_spec(result):
    result = _coerce_to_distributions(result)
    if result.is_unswept():
        return RenderSpec("bar", "Outcome", "Probability")
    if len(result.axes) == 1:
        axis_name = _fallback_axis_name(result.axes[0], 0)
        if _all_scalar(result):
            return RenderSpec("line", axis_name, "Value")
        return RenderSpec("heatmap_distribution", axis_name, "Outcome")
    if len(result.axes) == 2 and _all_scalar(result):
        return RenderSpec(
            "heatmap_scalar",
            _fallback_axis_name(result.axes[1], 1),
            _fallback_axis_name(result.axes[0], 0),
        )
    raise Exception("Viewer exception: render does not support this result shape yet")


def build_comparison_spec(entries):
    labels, raw_results = zip(*entries)
    results = [_coerce_to_distributions(result) for result in raw_results]

    if all(result.is_unswept() for result in results):
        _validate_outcome_domains(results)
        return RenderSpec("compare_bar", "Outcome", "Probability", tuple(labels)), results

    if all(len(result.axes) == 1 and _all_scalar(result) for result in results):
        _validate_same_axis_values(results)
        return RenderSpec("compare_line", _common_axis_name(results), "Value", tuple(labels)), results

    raise Exception("Viewer exception: render comparison only supports unswept distributions or one-sweep scalar results")


def _probability_scale(render_config=None):
    config = render_config if render_config is not None else RenderConfig()
    return config.probability_scale(default="percent")


def _probability_label(render_config=None):
    config = render_config if render_config is not None else RenderConfig()
    return config.probability_axis_label(default="percent")


def _cell_lookup(result):
    return dict(result.items())


def _record(payload):
    _RENDER_PAYLOADS.append(payload)
    return payload


def render_result(result, label=None, x_label=None, title=None, render_config=None):
    result = _coerce_to_distributions(result)
    spec = build_render_spec(result)
    scale = _probability_scale(render_config)

    payload = {
        "kind": spec.kind,
        "spec": {
            "kind": spec.kind,
            "x_label": x_label if x_label is not None else spec.x_label,
            "y_label": spec.y_label if spec.kind != "bar" else _probability_label(render_config),
            "series_labels": list(spec.series_labels),
        },
        "title": title,
    }

    if spec.kind == "bar":
        distrib = result.only_distribution()
        outcomes = _ordered_values(distrib.keys())
        payload["categories"] = list(outcomes)
        payload["series"] = [
            {
                "name": label or "Probability",
                "values": [distrib[outcome] * scale for outcome in outcomes],
            }
        ]
    elif spec.kind == "line":
        axis = result.axes[0]
        lookup = _cell_lookup(result)
        payload["categories"] = list(axis.values)
        payload["series"] = [
            {
                "name": label or "Value",
                "values": [_scalar_value(lookup[(value,)]) for value in axis.values],
            }
        ]
    elif spec.kind == "heatmap_distribution":
        axis = result.axes[0]
        lookup = _cell_lookup(result)
        outcomes = []
        seen = set()
        for value in axis.values:
            for outcome in _ordered_values(lookup[(value,)].keys()):
                if outcome not in seen:
                    outcomes.append(outcome)
                    seen.add(outcome)
        matrix = []
        for outcome in outcomes:
            row = []
            for value in axis.values:
                row.append(lookup[(value,)][outcome] * scale)
            matrix.append(row)
        payload["x_values"] = list(axis.values)
        payload["y_values"] = outcomes
        payload["matrix"] = matrix
        payload["color_label"] = _probability_label(render_config)
    elif spec.kind == "heatmap_scalar":
        y_axis = result.axes[0]
        x_axis = result.axes[1]
        lookup = _cell_lookup(result)
        matrix = []
        for y_value in y_axis.values:
            row = []
            for x_value in x_axis.values:
                row.append(_scalar_value(lookup[(y_value, x_value)]))
            matrix.append(row)
        payload["x_values"] = list(x_axis.values)
        payload["y_values"] = list(y_axis.values)
        payload["matrix"] = matrix
        payload["color_label"] = "Value"
    else:
        raise Exception("Viewer exception: unsupported render kind {}".format(spec.kind))

    _record(payload)
    return RenderOutcome(spec, "__dice_web_render__")


def render_comparison(entries, x_label=None, title=None, render_config=None):
    spec, results = build_comparison_spec(entries)
    scale = _probability_scale(render_config)
    payload = {
        "kind": spec.kind,
        "spec": {
            "kind": spec.kind,
            "x_label": x_label if x_label is not None else spec.x_label,
            "y_label": spec.y_label if spec.kind != "compare_bar" else _probability_label(render_config),
            "series_labels": list(spec.series_labels),
        },
        "title": title,
    }

    if spec.kind == "compare_bar":
        all_outcomes = []
        seen = set()
        for result in results:
            for outcome in _ordered_values(result.only_distribution().keys()):
                if outcome not in seen:
                    all_outcomes.append(outcome)
                    seen.add(outcome)
        payload["categories"] = list(all_outcomes)
        payload["series"] = []
        for label, result in zip(spec.series_labels, results):
            distrib = result.only_distribution()
            payload["series"].append(
                {
                    "name": label,
                    "values": [distrib[outcome] * scale for outcome in all_outcomes],
                }
            )
    elif spec.kind == "compare_line":
        x_values = results[0].axes[0].values
        payload["categories"] = list(x_values)
        payload["series"] = []
        for label, result in zip(spec.series_labels, results):
            payload["series"].append(
                {
                    "name": label,
                    "values": [_scalar_value(result.cells[(value,)]) for value in x_values],
                }
            )
    else:
        raise Exception("Viewer exception: unsupported comparison render kind {}".format(spec.kind))

    _record(payload)
    return RenderOutcome(spec, "__dice_web_render__")
