# Managed runtime shutdown

Shutdown is structured and idempotent: stop producers, join controllers, close orchestration groups, then release shared execution resources. Cleanup errors are surfaced without skipping later cleanup stages.

Downstream code owns neither shutdown ordering nor controller cancellation. Scientific facts already committed to the Machine Journal remain valid even if infrastructure cleanup subsequently fails.
