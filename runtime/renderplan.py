#!/usr/bin/env python3

"""Backend-neutral render planning for dice charts and reports."""

from __future__ import annotations

from dataclasses import dataclass

from diceengine import (
    ChartSpec,
    PanelWidthClass,
    RenderConfig,
    ReportBlock,
    ReportSpec,
    TupleValue,
    _coerce_to_distributions,
)


@dataclass(frozen=True)
class ChartRenderPlan:
    kind: str
    width_class: str
    payload: object
    x_label: str | None = None
    y_label: str | None = None
    title: str | None = None
    hints: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class ReportRenderPlan:
    title: str | None
    hero: ChartRenderPlan | None
    rows: tuple[tuple[ChartRenderPlan, ...], ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class RenderOutcome:
    plan: object
    result: object
    output_path: str | None = None


_TAIL_CLIP_MASS = 0.001


def _is_scalar_distribution(distrib):
    items = list(distrib.items())
    return len(items) == 1 and items[0][1] == 1 and isinstance(items[0][0], (int, float))


def _all_scalar(result):
    return all(_is_scalar_distribution(distrib) for distrib in result.cells.values())


def _ordered_values(values):
    try:
        return tuple(sorted(values))
    except TypeError:
        return tuple(values)


def _central_probability_window(distrib):
    outcomes = _ordered_values(distrib.keys())
    if len(outcomes) < 25 or not all(isinstance(outcome, (int, float)) for outcome in outcomes):
        return outcomes, None
    probabilities = [distrib[outcome] for outcome in outcomes]
    left_index = 0
    right_index = len(outcomes) - 1
    removed_mass = 0.0
    while left_index < right_index:
        left_mass = probabilities[left_index]
        right_mass = probabilities[right_index]
        if removed_mass + min(left_mass, right_mass) > _TAIL_CLIP_MASS:
            break
        if left_mass <= right_mass:
            removed_mass += left_mass
            left_index += 1
        else:
            removed_mass += right_mass
            right_index -= 1
    if left_index == 0 and right_index == len(outcomes) - 1:
        return outcomes, None
    kept = outcomes[left_index : right_index + 1]
    if not kept:
        return outcomes, None
    return kept, "Showing central 99.9% of mass; tails omitted."


def _dominant_zero_probability(distrib, render_config):
    if render_config is not None and not render_config.omit_dominant_zero_outcome:
        return None
    if 0 not in distrib.keys():
        return None
    if not all(isinstance(outcome, (int, float)) for outcome in distrib.keys()):
        return None
    other_outcomes = [outcome for outcome in distrib.keys() if outcome != 0]
    if len(other_outcomes) < 2:
        return None
    zero_probability = distrib[0]
    highest_other = max(distrib[outcome] for outcome in other_outcomes)
    if zero_probability < 0.2 or zero_probability < highest_other * 2:
        return None
    return zero_probability


def _build_distribution_hints(distrib, x_label, *, clip_tails, render_config=None):
    hints = []
    if clip_tails:
        visible_outcomes, note = _central_probability_window(distrib)
        if note is not None:
            hints.append(
                {
                    "kind": "clip_outcomes",
                    "scope": "x_axis",
                    "visible_outcomes": visible_outcomes,
                    "reason": "central_probability_mass",
                    "note": note,
                    "tail_clip_mass": _TAIL_CLIP_MASS,
                }
            )
    zero_probability = _dominant_zero_probability(distrib, render_config)
    if zero_probability is not None:
        if isinstance(x_label, str) and x_label.strip():
            note = "0 {} omitted from scale: {:.0f}% at zero.".format(
                x_label.strip(),
                zero_probability * 100,
            )
        else:
            note = "0 omitted from scale: {:.0f}% at zero.".format(zero_probability * 100)
        hints.append(
            {
                "kind": "omit_outcome",
                "scope": "x_axis",
                "outcome": 0,
                "reason": "dominant_zero",
                "probability": zero_probability,
                "note": note,
            }
        )
    return tuple(hints)


def _build_compare_unswept_hints(results, x_label, render_config=None):
    zero_probabilities = {}
    for label, result in results:
        zero_probability = _dominant_zero_probability(result.only_distribution(), render_config)
        if zero_probability is not None:
            zero_probabilities[label] = zero_probability
    if not zero_probabilities:
        return ()
    hints = [
        {
            "kind": "omit_outcome",
            "scope": "x_axis",
            "outcome": 0,
            "reason": "dominant_zero",
            "note": "0 omitted from x-axis.",
        }
    ]
    for label, probability in zero_probabilities.items():
        hints.append(
            {
                "kind": "series_label_suffix",
                "label": label,
                "reason": "dominant_zero",
                "probability": probability,
                "suffix": " ({:.0f}% at zero)".format(probability * 100),
            }
        )
    return tuple(hints)


def _validate_series_entries(entries):
    normalized = []
    for entry in entries:
        if not isinstance(entry, TupleValue):
            raise Exception('comparison entries must be tuple literals like ("Label", value)')
        items = tuple(entry.items)
        if len(items) != 2:
            raise Exception("comparison entries must contain exactly two items")
        label, value = items
        if not isinstance(label, str):
            raise Exception("comparison entry labels must be strings")
        normalized.append((label, value))
    if len(normalized) < 2:
        raise Exception("comparisons require at least two labeled entries")
    return tuple(normalized)


def build_chart_plan(chart_spec, render_config=None):
    if not isinstance(chart_spec, ChartSpec):
        raise Exception("expected a chart spec")
    render_config = render_config if render_config is not None else RenderConfig()

    intent = chart_spec.intent
    payload = chart_spec.payload

    if intent in {"auto", "dist", "cdf", "surv", "best"}:
        result = _coerce_to_distributions(payload)
        width_class = PanelWidthClass.NARROW
        hints = ()
        if intent == "best":
            width_class = PanelWidthClass.WIDE
            return ChartRenderPlan(
                "best_strategy",
                width_class,
                result,
                chart_spec.x_label,
                chart_spec.y_label,
                chart_spec.title,
                hints,
            )
        if result.is_unswept():
            kind = "unswept_distribution" if intent in {"auto", "dist"} else intent
            if kind == "unswept_distribution":
                hints = _build_distribution_hints(
                    result.only_distribution(),
                    chart_spec.x_label,
                    clip_tails=True,
                    render_config=render_config,
                )
        elif len(result.axes) == 1:
            if _all_scalar(result):
                kind = "scalar_sweep"
            else:
                kind = "distribution_sweep"
                width_class = PanelWidthClass.WIDE
        elif len(result.axes) == 2 and _all_scalar(result):
            kind = "scalar_heatmap"
            width_class = PanelWidthClass.WIDE
        else:
            raise Exception("render does not support this result shape yet")
        if chart_spec.width_override is not None:
            width_class = chart_spec.width_override
        return ChartRenderPlan(
            kind,
            width_class,
            result,
            chart_spec.x_label,
            chart_spec.y_label,
            chart_spec.title,
            hints,
        )

    if intent in {"compare", "diff"}:
        normalized = _validate_series_entries(payload)
        results = [(label, _coerce_to_distributions(value)) for label, value in normalized]
        width_class = PanelWidthClass.NARROW
        hints = ()
        if intent == "diff":
            width_class = PanelWidthClass.WIDE
            plan_kind = "diff"
        else:
            if all(result.is_unswept() for _, result in results):
                plan_kind = "compare_unswept"
                if len(results) > 3:
                    width_class = PanelWidthClass.WIDE
                hints = _build_compare_unswept_hints(results, chart_spec.x_label, render_config=render_config)
            elif all(len(result.axes) == 1 and _all_scalar(result) for _, result in results):
                plan_kind = "compare_scalar"
            else:
                plan_kind = "compare_faceted"
                width_class = PanelWidthClass.WIDE
        if chart_spec.width_override is not None:
            width_class = chart_spec.width_override
        return ChartRenderPlan(
            plan_kind,
            width_class,
            tuple(results),
            chart_spec.x_label,
            chart_spec.y_label,
            chart_spec.title,
            hints,
        )

    raise Exception("unknown chart intent {}".format(intent))


def build_report_plan(report_spec, render_config=None):
    if not isinstance(report_spec, ReportSpec):
        raise Exception("expected a report spec")
    render_config = render_config if render_config is not None else RenderConfig()
    hero = build_chart_plan(report_spec.hero, render_config=render_config) if report_spec.hero is not None else None
    rows = []
    pending_narrow = []
    notes = []

    def flush_pending():
        nonlocal pending_narrow
        if pending_narrow:
            rows.append(tuple(pending_narrow))
            pending_narrow = []

    for block in report_spec.blocks:
        if not isinstance(block, ReportBlock):
            raise Exception("invalid report block")
        if block.kind == "note":
            notes.append(block.value)
            continue
        if block.kind == "row":
            flush_pending()
            rows.append(tuple(build_chart_plan(chart, render_config=render_config) for chart in block.value))
            continue
        if block.kind == "panel":
            plan = build_chart_plan(block.value, render_config=render_config)
            if plan.width_class == PanelWidthClass.WIDE:
                flush_pending()
                rows.append((plan,))
            else:
                pending_narrow.append(plan)
                if len(pending_narrow) == 2:
                    flush_pending()
            continue
        raise Exception("unknown report block {}".format(block.kind))

    flush_pending()
    return ReportRenderPlan(report_spec.title, hero, tuple(rows), tuple(notes))
