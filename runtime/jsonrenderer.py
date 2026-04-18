#!/usr/bin/env python3

"""JSON render backend for chart/report plans."""

from __future__ import annotations

import json

from diceengine import RenderConfig
from renderplan import RenderOutcome, build_chart_plan, build_report_plan
from resultjson import serialize_result


_SINGLE_RESULT_PLAN_KINDS = {
    "unswept_distribution",
    "cdf",
    "surv",
    "scalar_sweep",
    "distribution_sweep",
    "scalar_heatmap",
    "best_strategy",
}


def wait_for_rendered_figures(render_config=None):
    return None


def _normalize_output_format(output_format):
    normalized = "json" if output_format is None else output_format.strip().lower()
    if normalized != "json":
        raise Exception("render format must be json for the json render backend")
    return normalized


def _serialize_chart_payload(plan, probability_mode):
    if plan.kind in _SINGLE_RESULT_PLAN_KINDS:
        return serialize_result(plan.payload, probability_mode=probability_mode)
    return [
        {
            "label": label,
            "result": serialize_result(result, probability_mode=probability_mode),
        }
        for label, result in plan.payload
    ]


def serialize_chart_plan(plan, probability_mode="raw"):
    return {
        "kind": plan.kind,
        "width_class": plan.width_class,
        "x_label": plan.x_label,
        "y_label": plan.y_label,
        "title": plan.title,
        "hints": list(plan.hints),
        "payload": _serialize_chart_payload(plan, probability_mode),
    }


def serialize_report_plan(plan, probability_mode="raw"):
    return {
        "title": plan.title,
        "hero": (
            serialize_chart_plan(plan.hero, probability_mode=probability_mode)
            if plan.hero is not None
            else None
        ),
        "rows": [
            [serialize_chart_plan(chart, probability_mode=probability_mode) for chart in row]
            for row in plan.rows
        ],
        "notes": list(plan.notes),
    }


def _render_payload_text(payload, path=None):
    text = json.dumps(payload, indent=2)
    if path is not None:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path, path
    return text, None


def render_chart(chart_spec, *, render_config=None, path=None, output_format="json", dpi=None):
    del dpi
    _normalize_output_format(output_format)
    render_config = render_config if render_config is not None else RenderConfig()
    probability_mode = render_config.effective_probability_mode(default="percent")
    plan = build_chart_plan(chart_spec)
    rendered, output_path = _render_payload_text(
        {
            "type": "chart",
            "format": "dice.render_plan.v1",
            "backend": "json",
            "chart": serialize_chart_plan(plan, probability_mode=probability_mode),
        },
        path=path,
    )
    return RenderOutcome(plan, rendered, output_path=output_path)


def render_report(report_spec, *, render_config=None, path=None, output_format="json", dpi=None):
    del dpi
    _normalize_output_format(output_format)
    render_config = render_config if render_config is not None else RenderConfig()
    probability_mode = render_config.effective_probability_mode(default="percent")
    plan = build_report_plan(report_spec)
    rendered, output_path = _render_payload_text(
        {
            "type": "report",
            "format": "dice.render_plan.v1",
            "backend": "json",
            "report": serialize_report_plan(plan, probability_mode=probability_mode),
        },
        path=path,
    )
    return RenderOutcome(plan, rendered, output_path=output_path)
