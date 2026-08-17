"""What the session cost, from the usage the transcript already records.

Cache reads dominate long sessions and are invisible in any per-message view:
a session can read a quarter of a billion cached tokens and show almost no
`input_tokens` at all. That is the number people are surprised by.
"""

from __future__ import annotations

from dataclasses import dataclass

# USD per million tokens. Cache write is 1.25x input, cache read is 0.1x.
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5":   (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-fable-5":  (10.00, 50.00),
}
CACHE_WRITE_MULT = 1.25
CACHE_READ_MULT = 0.10


@dataclass
class Cost:
    model: str = ""
    input_tokens: int = 0
    cache_write: int = 0
    cache_read: int = 0
    output_tokens: int = 0
    known_pricing: bool = True

    @property
    def total_input(self) -> int:
        return self.input_tokens + self.cache_write + self.cache_read

    @property
    def usd(self) -> float:
        rates = PRICING.get(self.model)
        if rates is None:
            return 0.0
        inp, out = rates
        return (self.input_tokens * inp
                + self.cache_write * inp * CACHE_WRITE_MULT
                + self.cache_read * inp * CACHE_READ_MULT
                + self.output_tokens * out) / 1e6

    @property
    def cache_share(self) -> float:
        """How much of the input was re-read context rather than new material."""
        return self.cache_read / self.total_input if self.total_input else 0.0

    def add(self, model: str, usage: dict) -> None:
        if model and not model.startswith("<"):
            self.model = model
            if model not in PRICING:
                self.known_pricing = False
        self.input_tokens += int(usage.get("input_tokens") or 0)
        self.cache_write += int(usage.get("cache_creation_input_tokens") or 0)
        self.cache_read += int(usage.get("cache_read_input_tokens") or 0)
        self.output_tokens += int(usage.get("output_tokens") or 0)
