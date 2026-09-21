# Trial / Attempt Identity Executable Invariant

Scientific trial identity is stable across infrastructure retries. Every execution attempt receives a distinct attempt identity linked to exactly one trial identity. Retry policy may create attempts but must never silently increase repetitions or alter the experiment matrix.