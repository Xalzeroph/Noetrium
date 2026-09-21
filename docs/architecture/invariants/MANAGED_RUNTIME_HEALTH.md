# Managed runtime health

Runtime health is an operational assertion over owned controllers and resource groups. A failed background controller must surface synchronously through the managed runtime health boundary; it must not be hidden behind a degraded flag while new scientific work continues.

Health status is diagnostic state, not Machine Journal truth. Scientific execution records the effects and failures that occurred through canonical receipts.
