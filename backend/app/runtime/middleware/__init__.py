"""Leaf middleware the graph is assembled from.

Each module imports only `app.exceptions` from the application and must stay
that way, so the graph assembly can be tested with no DB, network or sandbox.
"""
