"""Durable agent runtime.

A run is a Redis-backed execution envelope around one agent turn: it has a
lifecycle, an append-only event log, and a control channel, so the HTTP request
that started it is a thin subscriber the run outlives. See `SPEC.md`.
"""
